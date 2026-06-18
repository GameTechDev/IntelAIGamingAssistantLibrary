from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests


DEFAULT_SERVICE_HOST = "127.0.0.1:9190"
_KNOWLEDGE_ID_SAFE_PATTERN = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]+")


class WalkthroughServiceImportError(RuntimeError):
    pass


@dataclass(slots=True)
class WalkthroughTextImageEntry:
    text: str
    images: tuple[str, ...]
    url: str
    text_id: str


@dataclass(slots=True)
class KnowledgeQueryResult:
    text_ids: list[str]
    message: str
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class MMRQueryHit:
    score: float
    document_id: str
    text: str
    info: dict[str, Any]


@dataclass(slots=True)
class VisionQueryHit:
    scene_id: str
    picture_id: str
    score: float


@dataclass(slots=True)
class WalkthroughImportSummary:
    instance_id: str
    knowledge_id: str
    vision_instance_id: str
    source_json: str
    scene_text_map_file: str
    texts_total: int
    texts_inserted: int
    texts_skipped: int
    mmr_records_total: int
    mmr_records_inserted: int
    mmr_records_skipped: int
    vision_scenes_total: int
    vision_scenes_inserted: int
    vision_scenes_skipped: int
    force_reimport: bool = False
    texts_deleted: int = 0
    mmr_records_deleted: int = 0
    vision_scenes_deleted: int = 0
    knowledge_build_events: list[dict[str, Any]] = field(default_factory=list)
    vision_build_events: list[dict[str, Any]] = field(default_factory=list)


class WalkthroughServiceImporter:
    def __init__(
        self,
        host: str = DEFAULT_SERVICE_HOST,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        knowledge_batch_size: int = 500,  # 知识文本默认批量大小
        vision_batch_size: int = 500,  # vision图片默认批量大小
    ) -> None:
        self._base_url = _normalize_base_url(host)
        self._session = session or requests.Session()
        self._timeout = timeout
        self._knowledge_batch_size = knowledge_batch_size  # 保存知识文本批量大小
        self._vision_batch_size = vision_batch_size  # 保存vision图片批量大小

    def close(self) -> None:
        self._session.close()

    def list_vision_instance_ids(self) -> set[str]:
        payload_data = self._get_json(f"{self._base_url}/vision/service/list")
        raw = payload_data.get("data", {}).get("instances_id", [])
        return {str(item).strip() for item in raw if str(item).strip()}

    def sync_from_json(
        self,
        instance_id: str,
        json_file_path: str | Path,
        *,
        force_reimport: bool = False,
        verbose: bool = False,
    ) -> WalkthroughImportSummary:
        json_path = Path(json_file_path).expanduser().resolve()
        entries = self._load_entries(json_path)
        knowledge_id = self._derive_knowledge_id(json_path)
        vision_instance_id = instance_id
        scene_text_map_path = self._write_scene_text_map(instance_id, json_path, entries)
        current_text_ids = [entry.text_id for entry in entries]
        current_record_keys = {
            self._make_record_key(entry.text_id, image_ref)
            for entry in entries
            for image_ref in (entry.images or ("",))
        }
        current_scene_ids = [entry.text_id for entry in entries]

        self._ensure_knowledge_instance(instance_id)
        existing_text_ids = self._list_existing_knowledge_text_ids(instance_id, knowledge_id)
        deleted_text_count = 0
        if force_reimport:
            text_ids_to_delete = [text_id for text_id in current_text_ids if text_id in existing_text_ids]
            if text_ids_to_delete:
                deleted_text_count = self._delete_knowledge_texts(instance_id, knowledge_id, text_ids_to_delete)
            entries_to_insert = entries
        else:
            entries_to_insert = [entry for entry in entries if entry.text_id not in existing_text_ids]

        if entries_to_insert:
            print(f"[knowledge] inserting {len(entries_to_insert)} text(s)", flush=True)
            if verbose:
                for index, entry in enumerate(entries_to_insert, start=1):
                    print(f"[knowledge]   {index}/{len(entries_to_insert)} text_id={entry.text_id}", flush=True)
            self._insert_knowledge_texts(instance_id, knowledge_id, entries_to_insert)
        else:
            print("[knowledge] no new texts to insert", flush=True)

        knowledge_build_events = self._build_knowledge(instance_id, full_build=force_reimport)

        self._ensure_vision_instance(vision_instance_id)
        existing_scene_ids = self._list_existing_vision_scene_ids(vision_instance_id)
        deleted_vision_scene_count = 0
        if force_reimport:
            scene_ids_to_delete = [scene_id for scene_id in current_scene_ids if scene_id in existing_scene_ids]
            if scene_ids_to_delete:
                deleted_vision_scene_count = self._delete_vision_scenes(vision_instance_id, scene_ids_to_delete)
            existing_scene_ids = set()

        inserted_scene_count = 0
        pending_scene_ids = [entry.text_id for entry in entries if entry.text_id not in existing_scene_ids]
        if pending_scene_ids:
            print(f"[vision] inserting {len(pending_scene_ids)} scene(s)", flush=True)
        for entry in entries:
            if entry.text_id in existing_scene_ids:
                continue
            self._insert_vision_scene(vision_instance_id, json_path, entry)
            existing_scene_ids.add(entry.text_id)
            inserted_scene_count += 1
            bar = _progress_bar(inserted_scene_count, len(pending_scene_ids))
            print(
                f"\r[vision] insert {bar} {inserted_scene_count}/{len(pending_scene_ids)} text_id={entry.text_id}",
                end="",
                flush=True,
            )
        if pending_scene_ids:
            print(flush=True)
        else:
            print("[vision] no new scenes to insert", flush=True)

        vision_build_events = self._build_vision(vision_instance_id, full_build=force_reimport)

        total_record_count = 0
        inserted_record_count = 0
        deleted_mmr_count = 0

        # self._ensure_mmr_instance(instance_id)
        # existing_records = self._list_existing_mmr_records(instance_id)
        # deleted_mmr_count = 0
        # if force_reimport:
        #     record_ids_to_delete = [
        #         record["document_id"]
        #         for record in existing_records
        #         if self._make_record_key(record["text_id"], record["source_image"]) in current_record_keys
        #     ]
        #     if record_ids_to_delete:
        #         deleted_mmr_count = self._delete_mmr_records(instance_id, record_ids_to_delete)
        #     existing_record_keys: set[tuple[str, str, str]] = set()
        # else:
        #     existing_record_keys = {
        #         self._make_record_key(record["text_id"], record["source_image"])
        #         for record in existing_records
        #         if record["text_id"]
        #     }
        # inserted_record_count = 0
        # total_record_count = 0

        # for entry_index, entry in enumerate(entries):
        #     image_refs = entry.images or ("",)
        #     for image_index, image_ref in enumerate(image_refs):
        #         total_record_count += 1
        #         record_key = self._make_record_key(entry.text_id, image_ref)
        #         if record_key in existing_record_keys:
        #             continue
        #         self._insert_mmr_record(
        #             instance_id=instance_id,
        #             json_path=json_path,
        #             knowledge_id=knowledge_id,
        #             entry=entry,
        #             entry_index=entry_index,
        #             image_ref=image_ref,
        #             image_index=image_index,
        #         )
        #         existing_record_keys.add(record_key)
        #         inserted_record_count += 1

        # self._build_mmr(instance_id)

        return WalkthroughImportSummary(
            instance_id=instance_id,
            knowledge_id=knowledge_id,
            vision_instance_id=vision_instance_id,
            source_json=_display_path(json_path),
            scene_text_map_file=_display_path(scene_text_map_path),
            force_reimport=force_reimport,
            texts_total=len(entries),
            texts_inserted=len(entries_to_insert),
            texts_skipped=0 if force_reimport else len(entries) - len(entries_to_insert),
            texts_deleted=deleted_text_count,
            mmr_records_total=total_record_count,
            mmr_records_inserted=inserted_record_count,
            mmr_records_skipped=0 if force_reimport else total_record_count - inserted_record_count,
            mmr_records_deleted=deleted_mmr_count,
            knowledge_build_events=knowledge_build_events,
            vision_scenes_total=len(entries),
            vision_scenes_inserted=inserted_scene_count,
            vision_scenes_skipped=0 if force_reimport else len(entries) - inserted_scene_count,
            vision_scenes_deleted=deleted_vision_scene_count,
            vision_build_events=vision_build_events,
        )

    def query_knowledge(
        self,
        instance_id: str,
        question: str,
        *,
        knowledge_ids: str | list[str] | None = None,
        text_ids: list[str] | None = None,
    ) -> KnowledgeQueryResult:
        payload: dict[str, Any] = {"text": question}
        if knowledge_ids is not None:
            payload["knowledge_id"] = [knowledge_ids] if isinstance(knowledge_ids, str) else knowledge_ids
        if text_ids:
            payload["texts_id"] = text_ids

        response = self._session.post(
            f"{self._base_url}/knowledge/service/query/{instance_id}",
            json=payload,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=self._timeout,
        )
        _ensure_http_success(response)

        events: list[dict[str, Any]] = []
        matched_text_ids: list[str] = []
        message_parts: list[str] = []
        for event in _iter_sse_json(response):
            _ensure_ok(event)
            events.append(event)
            data = event.get("data") or {}
            if "text_ids" in data:
                matched_text_ids = list(data.get("text_ids") or [])
            chunk = data.get("message")
            if chunk:
                message_parts.append(chunk)

        return KnowledgeQueryResult(text_ids=matched_text_ids, message="".join(message_parts), events=events)

    def query_mmr(
        self,
        instance_id: str,
        *,
        text: str = "",
        image_path: str | Path | None = None,
        topk: int = 3,
        threshold: float = 0.01,
    ) -> list[MMRQueryHit]:
        if not text and image_path is None:
            raise ValueError("text and image_path cannot both be empty")

        payload = {
            "instance_id": instance_id,
            "text": text,
            "topk": topk,
            "threshold": threshold,
        }
        files = None
        if image_path is not None:
            resolved_image = Path(image_path).expanduser().resolve()
            files = [("filedata", (resolved_image.name, resolved_image.read_bytes(), "application/octet-stream"))]

        response = self._session.post(
            f"{self._base_url}/mmr/service/query",
            data={"data": json.dumps(payload, ensure_ascii=False)},
            files=files,
            timeout=self._timeout,
        )
        _ensure_http_success(response)
        payload_data = response.json()
        _ensure_ok(payload_data)

        hits: list[MMRQueryHit] = []
        for group in payload_data.get("data") or []:
            for item in group:
                if not isinstance(item, list) or len(item) != 2:
                    continue
                score, document = item
                metadata = document.get("metadata") or {}
                hits.append(
                    MMRQueryHit(
                        score=float(score),
                        document_id=str(document.get("document_id") or ""),
                        text=str(metadata.get("text") or ""),
                        info=dict(metadata.get("info") or {}),
                    )
                )
        return hits

    def query_vision(
        self,
        instance_id: str,
        image_path: str | Path,
        *,
        topk: int = 3,
        threshold: float = -1.0,
        threshold_2: float = -1.0,
        mode: str = "accurate",
    ) -> list[VisionQueryHit]:
        resolved_image = Path(image_path).expanduser().resolve()
        response = self._session.post(
            f"{self._base_url}/vision/service/query/{instance_id}",
            data={
                "topk": str(topk),
                "threshold": str(threshold),
                "threshold_2": str(threshold_2),
                "mode": mode,
            },
            files={"file": (resolved_image.name, resolved_image.read_bytes(), "application/octet-stream")},
            timeout=self._timeout,
        )
        _ensure_http_success(response)
        payload_data = response.json()
        _ensure_ok(payload_data)
        return [
            VisionQueryHit(
                scene_id=str(item.get("scene_id") or ""),
                picture_id=str(item.get("picture_id") or ""),
                score=float(item.get("score") or 0.0),
            )
            for item in payload_data.get("data") or []
        ]

    def _ensure_knowledge_instance(self, instance_id: str) -> None:
        payload_data = self._get_json(f"{self._base_url}/knowledge/service/list")
        instance_ids = set(payload_data.get("data", {}).get("instances_id", []))
        if instance_id in instance_ids:
            return
        self._post_json(f"{self._base_url}/knowledge/service/init/{instance_id}")

    def _ensure_mmr_instance(self, instance_id: str) -> None:
        payload_data = self._get_json(f"{self._base_url}/mmr/service/list")
        instance_ids = set(payload_data.get("data", {}).get("instance_ids", []))
        if instance_id in instance_ids:
            return
        self._post_json(f"{self._base_url}/mmr/service/init", json_body={"instance_id": instance_id})

    def _ensure_vision_instance(self, instance_id: str) -> None:
        payload_data = self._get_json(f"{self._base_url}/vision/service/list")
        instance_ids = set(payload_data.get("data", {}).get("instances_id", []))
        if instance_id in instance_ids:
            return
        self._post_json(f"{self._base_url}/vision/service/init/{instance_id}")

    def _list_existing_knowledge_text_ids(self, instance_id: str, knowledge_id: str) -> set[str]:
        payload_data = self._get_json(f"{self._base_url}/knowledge/knowledge/list/{instance_id}")
        knowledge_ids = set(payload_data.get("data", {}).get("knowledge_ids", []))
        if knowledge_id not in knowledge_ids:
            return set()
        payload_data = self._get_json(f"{self._base_url}/knowledge/knowledge/text/list/{instance_id}/{knowledge_id}")
        return set(payload_data.get("data", {}).get("texts_id", []))

    def _list_existing_mmr_records(self, instance_id: str) -> list[dict[str, str]]:
        payload_data = self._post_json(f"{self._base_url}/mmr/record/list", json_body={"instance_id": instance_id})
        records: list[dict[str, str]] = []
        for record in payload_data.get("data", {}).get("record_ids", []):
            metadata = record.get("metadata") or {}
            info = metadata.get("info") or {}
            records.append(
                {
                    "document_id": str(record.get("document_id") or ""),
                    "text_id": str(info.get("text_id") or info.get("knowledge_text_id") or ""),
                    "source_image": str(info.get("source_image") or ""),
                }
            )
        return records

    def _delete_knowledge_texts(self, instance_id: str, knowledge_id: str, text_ids: list[str]) -> int:
        if not text_ids:
            return 0
        payload_data = self._post_json(
            f"{self._base_url}/knowledge/knowledge/text/delete/{instance_id}/{knowledge_id}",
            json_body={"texts_id": text_ids},
        )
        return len(payload_data.get("data", {}).get("deleted", []))

    def _delete_mmr_records(self, instance_id: str, record_ids: list[str]) -> int:
        deleted_count = 0
        for record_id in record_ids:
            self._post_json(
                f"{self._base_url}/mmr/record/delete",
                json_body={"instance_id": instance_id, "record_id": record_id},
            )
            deleted_count += 1
        return deleted_count

    def _list_existing_vision_scene_ids(self, instance_id: str) -> set[str]:
        payload_data = self._get_json(f"{self._base_url}/vision/scene/list/{instance_id}")
        return set(payload_data.get("data", {}).get("scenes_id", []))

    def _delete_vision_scenes(self, instance_id: str, scene_ids: list[str]) -> int:
        deleted_count = 0
        for scene_id in scene_ids:
            self._post_json(f"{self._base_url}/vision/scene/delete/{instance_id}/{scene_id}")
            deleted_count += 1
        return deleted_count

    def _insert_knowledge_texts(
        self,
        instance_id: str,
        knowledge_id: str,
        entries: list[WalkthroughTextImageEntry],
    ) -> None:
        # 使用实例的知识文本批量大小
        for i in range(0, len(entries), self._knowledge_batch_size):
            batch = entries[i:i+self._knowledge_batch_size]
            form_data: list[tuple[str, str]] = []
            metadata: dict[str, dict[str, Any]] = {}
            files: list[tuple[str, tuple[str, bytes, str]]] = []

            for entry in batch:
                form_data.append(("texts_id", entry.text_id))
                metadata[entry.text_id] = {}
                files.append(
                    (
                        "texts",
                        (f"{entry.text_id}.txt", entry.text.encode("utf-8"), "text/plain; charset=utf-8"),
                    )
                )

            form_data.append(("texts_metadata", json.dumps(metadata, ensure_ascii=False)))
            response = self._session.post(
                f"{self._base_url}/knowledge/knowledge/insert/{instance_id}/{knowledge_id}",
                data=form_data,
                files=files,
                timeout=self._timeout,
            )
            _ensure_http_success(response)
            _ensure_ok(response.json())

    def _insert_vision_scene(self, instance_id: str, json_path: Path, entry: WalkthroughTextImageEntry) -> None:
        picture_ids = [image_ref for image_ref in entry.images]
        for i in range(0, len(picture_ids), self._vision_batch_size):
            batch = picture_ids[i:i+self._vision_batch_size]
            files = [
                (
                    "pictures",
                    (
                        Path(image_ref).name,
                        _resolve_image_path(json_path, image_ref).read_bytes(),
                        "application/octet-stream",
                    ),
                )
                for image_ref in batch
            ]
            response = self._session.post(
                f"{self._base_url}/vision/scene/insert/{instance_id}/{entry.text_id}",
                data=[("pictures_id", picture_id) for picture_id in batch] + [("mode", "accurate")],
                files=files,
                timeout=self._timeout,
            )
            _ensure_http_success(response)
            payload_data = response.json()
            _ensure_ok(payload_data)
            invalid_pictures = payload_data.get("data", {}).get("invalid_pictures", [])
            if invalid_pictures:
                invalid_names = ", ".join(str(item.get("name") or "") for item in invalid_pictures)
                raise WalkthroughServiceImportError(f"vision insert reported invalid pictures for scene {entry.text_id}: {invalid_names}")

    def _build_knowledge(self, instance_id: str, *, full_build: bool) -> list[dict[str, Any]]:
        response = self._session.post(
            f"{self._base_url}/knowledge/service/build/{instance_id}",
            json={"full_build": full_build},
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=self._timeout,
        )
        _ensure_http_success(response)

        events: list[dict[str, Any]] = []
        build_errors: list[str] = []
        event_count = 0
        for event in _iter_sse_json(response):
            _ensure_ok(event)
            events.append(event)
            event_count += 1
            data = event.get("data") or {}
            event_name = str(data.get("event_name") or "")
            progress = _extract_event_progress(data)
            if progress is not None:
                current, total = progress
                bar = _progress_bar(current, total)
                print(f"\r[knowledge] build {bar} {current}/{total} {event_name}", end="", flush=True)
            else:
                print(f"\r[knowledge] build event {event_count}: {event_name or 'processing'}", end="", flush=True)
            if event_name == "build_error":
                text_id = str(data.get("text_id") or "")
                build_errors.append(text_id)

        print(flush=True)

        if build_errors:
            raise WalkthroughServiceImportError(f"knowledge build failed for text ids: {', '.join(build_errors)}")
        return events

    def _insert_mmr_record(
        self,
        *,
        instance_id: str,
        json_path: Path,
        knowledge_id: str,
        entry: WalkthroughTextImageEntry,
        entry_index: int,
        image_ref: str,
        image_index: int,
    ) -> None:
        payload = {
            "instance_id": instance_id,
            "text": entry.text,
            "info": {
                "instance_id": instance_id,
                "knowledge_id": knowledge_id,
                "text_id": entry.text_id,
                "knowledge_text_id": entry.text_id,
                "source_json": _display_path(json_path),
                "source_image": image_ref,
                "datapath": image_ref,
                "entry_index": entry_index,
                "image_index": image_index,
            },
        }

        files = None
        if image_ref:
            image_path = _resolve_image_path(json_path, image_ref)
            files = [("filedata", (image_path.name, image_path.read_bytes(), "application/octet-stream"))]

        response = self._session.post(
            f"{self._base_url}/mmr/record/insert",
            data={"data": json.dumps(payload, ensure_ascii=False)},
            files=files,
            timeout=self._timeout,
        )
        _ensure_http_success(response)
        _ensure_ok(response.json())

    def _build_mmr(self, instance_id: str) -> None:
        self._post_json(f"{self._base_url}/mmr/service/build", json_body={"instance_id": instance_id})

    def _build_vision(self, instance_id: str, *, full_build: bool) -> list[dict[str, Any]]:
        response = self._session.post(
            f"{self._base_url}/vision/service/build/{instance_id}",
            json={"mode": "accurate", "full_build": full_build, "auto_threshold": True},
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=self._timeout,
        )
        _ensure_http_success(response)
        events: list[dict[str, Any]] = []
        build_errors: list[str] = []
        event_count = 0
        for event in _iter_sse_json(response):
            _ensure_ok(event)
            events.append(event)
            event_count += 1
            data = event.get("data") or {}
            event_name = str(data.get("event_name") or "")
            progress = _extract_event_progress(data)
            if progress is not None:
                current, total = progress
                bar = _progress_bar(current, total)
                print(f"\r[vision] build    {bar} {current}/{total} {event_name}", end="", flush=True)
            else:
                print(f"\r[vision] build event {event_count}: {event_name or 'processing'}", end="", flush=True)
            if event_name == "build_error":
                picture_id = str(data.get("picture_id") or "")
                build_errors.append(picture_id)
        print(flush=True)
        if build_errors:
            raise WalkthroughServiceImportError(f"vision build failed for picture ids: {', '.join(build_errors)}")
        return events

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self._session.get(url, timeout=self._timeout)
        _ensure_http_success(response)
        payload_data = response.json()
        _ensure_ok(payload_data)
        return payload_data

    def _post_json(self, url: str, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._session.post(url, json=json_body, timeout=self._timeout)
        _ensure_http_success(response)
        payload_data = response.json()
        _ensure_ok(payload_data)
        return payload_data

    def _load_entries(self, json_path: Path) -> list[WalkthroughTextImageEntry]:
        payload_data = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(payload_data, list):
            raise ValueError("json content must be a list")

        entries: list[WalkthroughTextImageEntry] = []
        for item in payload_data:
            if not isinstance(item, dict):
                raise ValueError("each json item must be an object")
            text = str(item.get("text") or "").strip()
            images_value = item.get("images") or []
            url = str(item.get("url") or "").strip()
            if not isinstance(images_value, list):
                raise ValueError("images must be a list")
            if not text:
                raise ValueError("text cannot be empty")
            images = tuple(str(image).strip() for image in images_value if str(image).strip())
            entries.append(WalkthroughTextImageEntry(text=text, images=images, url=url, text_id=_sha256_text(text)))
        return entries

    def _write_scene_text_map(self, instance_id: str, json_path: Path, entries: list[WalkthroughTextImageEntry]) -> Path:
        mapping_path = json_path.with_name("scene_text_map.json")
        payload = {
            "instance_id": instance_id,
            "source_json": _display_path(json_path),
            "scene_id_to_text": {entry.text_id: entry.text for entry in entries},
            "scenes": [
                {
                    "scene_id": entry.text_id,
                    "text": entry.text,
                    "images": list(entry.images),
                    "url": entry.url,
                }
                for entry in entries
            ],
        }
        mapping_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return mapping_path

    def _derive_knowledge_id(self, json_path: Path) -> str:
        parts = [part for part in json_path.with_suffix("").parts if part not in {json_path.anchor, "."}]
        selected_parts = parts[-3:] if len(parts) >= 3 else parts
        normalized_parts = [_normalize_knowledge_id_part(part) for part in selected_parts if _normalize_knowledge_id_part(part)]
        return "__".join(normalized_parts)

    @staticmethod
    def _make_record_key(text_id: str, image_ref: str) -> tuple[str, str, str]:
        return text_id, image_ref, ""


def _normalize_base_url(host: str) -> str:
    normalized_host = host.rstrip("/")
    if normalized_host.startswith(("http://", "https://")):
        return normalized_host
    return f"http://{normalized_host}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_knowledge_id_part(value: str) -> str:
    normalized = _KNOWLEDGE_ID_SAFE_PATTERN.sub("_", value.strip())
    normalized = normalized.strip("_")
    return normalized


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_image_path(json_path: Path, image_ref: str) -> Path:
    image_path = Path(image_ref)
    if image_path.is_absolute() and image_path.exists():
        return image_path.resolve()

    for base_path in json_path.parents:
        candidate = (base_path / image_path).resolve()
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"unable to resolve image path: {image_ref}")


def _ensure_ok(payload_data: dict[str, Any]) -> None:
    if payload_data.get("code") == "ok":
        return
    raise WalkthroughServiceImportError(str(payload_data.get("msg") or "service request failed"))


def _ensure_http_success(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body_text = (response.text or "").strip().replace("\r", " ").replace("\n", " ")
        body_text = " ".join(body_text.split())[:240]
        detail = f"http {response.status_code} for {response.request.method} {response.url}"
        if body_text:
            detail = f"{detail}: {body_text}"
        raise WalkthroughServiceImportError(detail) from exc


def _iter_sse_json(response: requests.Response):
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        yield json.loads(payload)


def _progress_bar(current: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    ratio = max(0.0, min(1.0, current / total))
    filled = int(width * ratio)
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def _extract_event_progress(data: dict[str, Any]) -> tuple[int, int] | None:
    pairs = [
        ("progress", "total"),
        ("current", "total"),
        ("done", "total"),
        ("finished", "total"),
        ("index", "count"),
        ("step", "total_steps"),
    ]
    for current_key, total_key in pairs:
        current = data.get(current_key)
        total = data.get(total_key)
        if isinstance(current, (int, float)) and isinstance(total, (int, float)) and int(total) > 0:
            return int(current), int(total)
    return None


def run_import(
    instance_id: str,
    json_path: str | Path,
    force_reimport: bool = False,
    host: str = DEFAULT_SERVICE_HOST,
    timeout: float = 30.0,
    verbose: bool = False,
) -> WalkthroughImportSummary:
    if not str(instance_id).strip():
        raise ValueError("instance_id cannot be empty")

    importer = WalkthroughServiceImporter(host=host, timeout=timeout)
    try:
        return importer.sync_from_json(
            instance_id=instance_id,
            json_file_path=json_path,
            force_reimport=force_reimport,
            verbose=verbose,
        )
    finally:
        importer.close()


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import walkthrough text_images.json into knowledge and vision services.",
    )
    parser.add_argument(
        "json_path",
        help="Path to text_images.json",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_SERVICE_HOST,
        help=f"Service host, default: {DEFAULT_SERVICE_HOST}",
    )
    parser.add_argument(
        "--instance-id",
        required=True,
        help="Knowledge/Vision instance id.",
    )
    parser.add_argument(
        "--force-reimport",
        action="store_true",
        help="Delete existing matching records before import.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds, default: 30.0",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed insertion logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    json_path = Path(args.json_path).expanduser().resolve()
    if not json_path.exists():
        print(f"error: file not found: {json_path}", file=sys.stderr)
        return 2
    if not json_path.is_file():
        print(f"error: not a file: {json_path}", file=sys.stderr)
        return 2

    try:
        summary = run_import(
            instance_id=args.instance_id,
            json_path=json_path,
            force_reimport=args.force_reimport,
            host=args.host,
            timeout=args.timeout,
            verbose=args.verbose,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
