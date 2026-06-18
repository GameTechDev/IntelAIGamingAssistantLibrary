from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except ModuleNotFoundError as exc:
    requests = None
    BeautifulSoup = None
    Tag = Any
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_WALKTHROUGH_DIR = Path(__file__).resolve().parent.parent / "walkthrough"


@dataclass
class _Event:
    kind: str
    value: str


class GamerskyWalkthroughDownloader:
    """Download Gamersky game strategies and build text-image mapping JSON."""

    SEARCH_URL_TEMPLATE = "https://so.gamersky.com/all/handbook?s={query}&type=hot&sort=des"
    IMAGE_PROXY_PREFIX = "https://www.gamersky.com/showimage/id_gamersky.shtml?"
    PAGE_STOP_TEXT = "更多相关内容请关注"
    SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    def __init__(
        self,
        base_output_dir: str | Path = _DEFAULT_WALKTHROUGH_DIR,
        keywords: tuple[str, ...] = ("全地图", "100%", "白金攻略", "全收集", "图文攻略"),
        timeout: int = 20,
        max_pages: int | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._ensure_dependencies_available()
        self.base_output_dir = Path(base_output_dir)
        self.keywords = keywords
        self.timeout = timeout
        self.max_pages = max_pages
        self.progress_callback = progress_callback
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
        )

    def download_walkthrough(self, game_name: str) -> list[dict[str, Any]]:
        """
        Download all pages of the selected walkthrough, save assets to disk,
        and return the final text-image mapping.
        """
        walkthrough_url = self._find_walkthrough_url(game_name)

        game_dir_name = self._safe_name(game_name)
        game_dir = self.base_output_dir / game_dir_name
        game_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = game_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        mapping_path = game_dir / "text_images.json"
        state_path = game_dir / "download_state.json"

        mapping = self._load_mapping(mapping_path)
        mapping_changed = self._normalize_mapping_image_paths(mapping, game_dir_name)
        state = self._load_state(state_path)
        downloaded_pages = set(state.get("downloaded_pages", []))
        image_url_map: dict[str, str] = dict(state.get("image_url_map", {}))

        self._print_progress(f"开始下载攻略: {game_name}")
        self._print_progress(f"输出目录: {game_dir.as_posix()}")
        self._print_progress(f"历史已下载页面: {len(downloaded_pages)}")

        page_index = 0
        new_page_count = 0
        skipped_page_count = 0
        attempted_download_page_count = 0
        new_text_count = 0
        new_image_count = 0
        reused_image_count = 0
        skipped_image_count = 0

        max_pages = self.max_pages

        for page_url in self._iterate_pages(walkthrough_url):
            page_index += 1
            self._print_progress(f"处理第{page_index}页: {page_url}")
            if page_url in downloaded_pages:
                skipped_page_count += 1
                self._print_progress(f"已下载过第{page_index}页，跳过")
                continue

            if max_pages is not None and attempted_download_page_count >= max_pages:
                self._print_progress(f"达到页面下载上限 {max_pages}，停止继续下载")
                break

            attempted_download_page_count += 1

            html = self._get_html(page_url)
            soup = BeautifulSoup(html, "html.parser")
            content = soup.find("div", class_="Mid2L_con")
            if not isinstance(content, Tag):
                downloaded_pages.add(page_url)
                self._save_state(state_path, downloaded_pages, image_url_map)
                self._print_progress("未找到正文容器 Mid2L_con，标记后跳过")
                continue

            page_dir = pages_dir / f"page_{page_index}"
            page_texts_dir = page_dir / "texts"
            page_images_dir = page_dir / "images"
            page_rel_prefix = f"{game_dir_name}/pages/page_{page_index}/"
            page_texts_dir.mkdir(parents=True, exist_ok=True)
            page_images_dir.mkdir(parents=True, exist_ok=True)

            image_counter = self._next_index(page_images_dir, "image_", "*")
            text_counter = self._next_index(page_texts_dir, "text_", ".txt")

            page_events = self._extract_events(content)
            normalized_events: list[_Event] = []
            page_text_count = 0
            page_new_image_count = 0
            page_reused_image_count = 0
            page_skipped_image_count = 0
            for event in page_events:
                if event.kind == "text":
                    normalized_events.append(event)
                    text_path = page_texts_dir / f"text_{text_counter:04d}.txt"
                    text_path.write_text(event.value, encoding="utf-8")
                    text_counter += 1
                    page_text_count += 1
                    new_text_count += 1
                else:
                    image_url = event.value
                    if not self._is_supported_image_url(image_url):
                        page_skipped_image_count += 1
                        skipped_image_count += 1
                        self._print_progress(f"图片映射(跳过): {image_url} -> URL 末尾不是受支持的图片扩展名")
                        continue

                    cached_path = image_url_map.get(image_url)
                    if (
                        cached_path
                        and self._cached_image_exists(cached_path)
                        and self._to_game_relative_image_path(cached_path, game_dir_name).startswith(page_rel_prefix)
                    ):
                        event.value = self._to_game_relative_image_path(cached_path, game_dir_name)
                        image_url_map[image_url] = event.value
                        self._print_progress(
                            f"图片映射(复用): {image_url} -> {Path(event.value).name} ({event.value})"
                        )
                        normalized_events.append(event)
                        page_reused_image_count += 1
                        reused_image_count += 1
                        continue

                    suffix = self._guess_suffix(image_url)
                    image_path = page_images_dir / f"image_{image_counter:04d}{suffix}"
                    self._download_binary(image_url, image_path)
                    image_counter += 1
                    event.value = self._to_game_relative_image_path(image_path.as_posix(), game_dir_name)
                    image_url_map[image_url] = event.value
                    self._print_progress(
                        f"图片映射(下载): {image_url} -> {image_path.name} ({event.value})"
                    )
                    normalized_events.append(event)
                    page_new_image_count += 1
                    new_image_count += 1

            page_mapping = self._build_mapping(normalized_events, page_url)
            if page_mapping:
                mapping.extend(page_mapping)
            new_page_count += 1

            downloaded_pages.add(page_url)
            mapping_path.write_text(
                json.dumps(mapping, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            self._save_state(state_path, downloaded_pages, image_url_map)
            self._print_progress(
                "本页完成: "
                f"文本{page_text_count}段, "
                f"新图{page_new_image_count}张, "
                f"复用图{page_reused_image_count}张, "
                f"跳过图{page_skipped_image_count}张, "
                f"新增映射{len(page_mapping)}条"
            )

        if not mapping_path.exists():
            mapping_path.write_text("[]", encoding="utf-8")
        elif mapping_changed:
            mapping_path.write_text(
                json.dumps(mapping, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
        if not state_path.exists():
            self._save_state(state_path, downloaded_pages, image_url_map)
        self._print_progress(
            "下载结束: "
            f"扫描{page_index}页, "
            f"新处理{new_page_count}页, "
            f"跳过{skipped_page_count}页, "
            f"新增文本{new_text_count}段, "
            f"新增图片{new_image_count}张, "
            f"复用图片{reused_image_count}张, "
            f"跳过图片{skipped_image_count}张, "
            f"当前映射总数{len(mapping)}条"
        )
        return mapping

    def _find_walkthrough_url(self, game_name: str) -> str:
        query = quote(game_name, safe="")
        search_url = self.SEARCH_URL_TEMPLATE.format(query=query)
        html = self._get_html(search_url)
        soup = BeautifulSoup(html, "html.parser")

        result_container = soup.find("div", class_="Mid2_L")
        if not isinstance(result_container, Tag):
            raise RuntimeError("未找到搜索结果容器 Mid2_L")

        for anchor in result_container.find_all("a", href=True):
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            if any(keyword in title for keyword in self.keywords):
                return urljoin(search_url, anchor["href"])

        raise RuntimeError("未找到包含关键词的攻略链接")

    def _iterate_pages(self, first_page_url: str):
        current = first_page_url
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            yield current

            html = self._get_html(current)
            soup = BeautifulSoup(html, "html.parser")
            pager = soup.find("div", class_="page_css")
            if not isinstance(pager, Tag):
                break

            next_url = ""
            for anchor in pager.find_all("a", href=True):
                text = anchor.get_text(strip=True)
                if "下一页" in text:
                    next_url = urljoin(current, anchor["href"])
                    break

            if not next_url:
                break
            current = next_url

    def _extract_events(self, content: Any) -> list[_Event]:
        events: list[_Event] = []
        block_tags = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]

        for node in content.find_all(block_tags):
            if not isinstance(node, Tag):
                continue

            classes = set(node.get("class") or [])
            if "GsImageLabel" in classes:
                image_url = self._extract_image_url(node)
                if image_url:
                    events.append(_Event(kind="image", value=image_url))
                continue

            text = self._clean_text(node.get_text("\n", strip=True))
            if text:
                if self.PAGE_STOP_TEXT in text:
                    break
                events.append(_Event(kind="text", value=text))

        return events

    def _extract_image_url(self, node: Any) -> str:
        anchor = node.find("a", href=True)
        if not isinstance(anchor, Tag):
            return ""

        href = (anchor.get("href") or "").strip()
        if not href:
            return ""

        if href.startswith(self.IMAGE_PROXY_PREFIX):
            raw = href[len(self.IMAGE_PROXY_PREFIX) :]
        elif "showimage/id_gamersky.shtml?" in href:
            raw = href.split("?", 1)[1]
        else:
            raw = href

        raw = unquote(raw)
        if raw.startswith("//"):
            return "https:" + raw
        return raw

    def _build_mapping(self, events: list[_Event], page_url: str) -> list[dict[str, Any]]:
        mapping: list[dict[str, Any]] = []
        pending_texts: list[str] = []

        for event in events:
            if event.kind == "text":
                pending_texts.append(event.value)
                continue

            if pending_texts:
                text_blob = "\n".join(pending_texts)
                pending_texts = []
                mapping.append({"text": text_blob, "images": [event.value], "url": page_url})
                continue

            if not mapping:
                mapping.append({"text": "", "images": [event.value], "url": page_url})
            else:
                mapping[-1]["images"].append(event.value)

        if pending_texts:
            trailing = "\n".join(pending_texts)
            if mapping:
                if mapping[-1]["text"]:
                    mapping[-1]["text"] += "\n\n" + trailing
                else:
                    mapping[-1]["text"] = trailing
            else:
                mapping.append({"text": trailing, "images": [], "url": page_url})

        return mapping

    def _download_binary(self, url: str, save_path: Path) -> None:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        save_path.write_bytes(response.content)

    def _cached_image_exists(self, cached_path: str) -> bool:
        path = Path(cached_path)
        if path.exists():
            return True
        return (self.base_output_dir / cached_path).exists()

    def _to_game_relative_image_path(self, raw_path: str, game_dir_name: str) -> str:
        text = raw_path.replace("\\", "/")
        marker = f"/{game_dir_name}/"
        idx = text.find(marker)
        if idx >= 0:
            return text[idx + 1 :]
        if text.startswith(game_dir_name + "/"):
            return text
        if text.startswith("images/"):
            return f"{game_dir_name}/{text}"
        filename = Path(text).name
        return f"{game_dir_name}/images/{filename}"

    def _normalize_mapping_image_paths(self, mapping: list[dict[str, Any]], game_dir_name: str) -> bool:
        changed = False
        for row in mapping:
            images = row.get("images")
            if not isinstance(images, list):
                continue
            normalized: list[str] = []
            for item in images:
                if not isinstance(item, str):
                    normalized.append(item)
                    continue
                current = self._to_game_relative_image_path(item, game_dir_name)
                normalized.append(current)
                if current != item:
                    changed = True
            row["images"] = normalized
        return changed

    def _print_progress(self, message: str) -> None:
        line = f"[walkthrough] {message}"
        print(line)
        if self.progress_callback is not None:
            self.progress_callback(line)

    @staticmethod
    def _ensure_dependencies_available() -> None:
        if _IMPORT_ERROR is None:
            return
        raise RuntimeError(
            "缺少运行依赖，请先安装: pip install requests beautifulsoup4"
        ) from _IMPORT_ERROR

    @staticmethod
    def _load_mapping(mapping_path: Path) -> list[dict[str, Any]]:
        if not mapping_path.exists():
            return []
        try:
            payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _load_state(state_path: Path) -> dict[str, Any]:
        if not state_path.exists():
            return {"downloaded_pages": [], "image_url_map": {}}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"downloaded_pages": [], "image_url_map": {}}
        if not isinstance(payload, dict):
            return {"downloaded_pages": [], "image_url_map": {}}
        pages = payload.get("downloaded_pages")
        image_map = payload.get("image_url_map")
        return {
            "downloaded_pages": pages if isinstance(pages, list) else [],
            "image_url_map": image_map if isinstance(image_map, dict) else {},
        }

    @staticmethod
    def _save_state(state_path: Path, downloaded_pages: set[str], image_url_map: dict[str, str]) -> None:
        payload = {
            "downloaded_pages": sorted(downloaded_pages),
            "image_url_map": image_url_map,
        }
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")

    @staticmethod
    def _next_index(directory: Path, prefix: str, suffix_pattern: str) -> int:
        max_index = 0
        normalized_suffix = suffix_pattern.lower()
        for item in directory.iterdir():
            if not item.is_file():
                continue
            if normalized_suffix != "*" and item.suffix.lower() != normalized_suffix:
                continue
            stem = item.stem
            if not stem.startswith(prefix):
                continue
            seq = stem[len(prefix) :]
            if seq.isdigit():
                max_index = max(max_index, int(seq))
        return max_index + 1

    def _get_html(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text:
            return ""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n")]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    @staticmethod
    def _safe_name(name: str) -> str:
        # Remove characters that are invalid in Windows file names.
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
        return cleaned or "unknown_game"

    @staticmethod
    def _guess_suffix(url: str) -> str:
        path = urlparse(url).path
        suffix = Path(path).suffix.lower()
        if suffix in GamerskyWalkthroughDownloader.SUPPORTED_IMAGE_SUFFIXES:
            return suffix
        return ".jpg"

    @staticmethod
    def _is_supported_image_url(url: str) -> bool:
        path = urlparse(url).path
        suffix = Path(path).suffix.lower()
        return suffix in GamerskyWalkthroughDownloader.SUPPORTED_IMAGE_SUFFIXES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载游民星空图文攻略并导出 text_images.json")
    parser.add_argument("game_name", help="要下载攻略的游戏名")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=_DEFAULT_WALKTHROUGH_DIR.as_posix(),
        type=str,
        help="保存目录，将在其下创建游戏子目录",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP 请求超时时间，单位秒，默认 20",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="本次最多下载的页面数，默认不限制",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_pages is not None and args.max_pages <= 0:
        print("参数错误: --max-pages 必须是正整数", file=sys.stderr)
        return 2

    downloader = GamerskyWalkthroughDownloader(
        base_output_dir=args.output_dir,
        timeout=args.timeout,
        max_pages=args.max_pages,
    )
    try:
        mapping = downloader.download_walkthrough(args.game_name)
    except Exception as exc:
        print(f"下载失败: {exc}", file=sys.stderr)
        return 1

    game_dir = Path(args.output_dir) / downloader._safe_name(args.game_name)
    print(
        "导出完成: "
        f"{len(mapping)} 条映射, "
        f"输出文件 {game_dir.joinpath('text_images.json').as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

