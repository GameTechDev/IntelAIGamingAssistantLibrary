"""
MMR service sample script.

What this sample demonstrates:
1. Generate local demo images.
2. Init one MMR instance.
3. Insert text-only, image-only, and text+image records.
4. Build the instance index.
5. Query by text and image.
6. List records and cleanup.

Before running:
- Ensure MMR service is up.
- Adjust HOST in mmr_api.py if needed.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

import mmr_api as api


def generate_demo_images(output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("mmr_1", "#EAF6FF", "#1E88E5", "circle"),
        ("mmr_2", "#FFF8E1", "#F4511E", "rect"),
        ("mmr_3", "#E8F5E9", "#43A047", "triangle"),
    ]

    width, height = 720, 420
    image_paths: list[str] = []

    for name, bg, fg, shape in specs:
        img = Image.new("RGB", (width, height), color=bg)
        draw = ImageDraw.Draw(img)

        if shape == "circle":
            draw.ellipse((220, 100, 500, 380), fill=fg, outline="#0D47A1", width=8)
        elif shape == "rect":
            draw.rounded_rectangle((180, 110, 540, 340), radius=28, fill=fg, outline="#BF360C", width=8)
        else:
            draw.polygon([(360, 70), (170, 350), (550, 350)], fill=fg, outline="#1B5E20", width=8)

        draw.text((24, 20), f"MMR Sample: {name}", fill="#111111")

        file_path = output_dir / f"{name}.png"
        img.save(file_path)
        image_paths.append(str(file_path))

    return image_paths


def _assert_ok(resp: dict, action: str) -> None:
    if resp.get("code") != "ok":
        raise RuntimeError(f"{action} failed: {resp}")


def run_sample() -> None:
    ts = int(time.time())
    instance_id = f"sample_mmr_inst_{ts}"

    script_dir = Path(__file__).resolve().parent
    image_dir = script_dir / "sample_images"
    image_paths = generate_demo_images(image_dir)

    print("[1/8] check enable status")
    resp = api.set_mmr_enable(None)
    print(resp)
    if resp.get("code") not in {"ok", "fail"}:
        raise RuntimeError(f"set_mmr_enable(None) unexpected: {resp}")

    print("[2/8] init instance")
    resp = api.init_mmr(instance_id)
    print(resp)
    _assert_ok(resp, "init_mmr")

    try:
        print("[3/8] insert text-only record")
        resp = api.insert_mmr_record(
            instance_id=instance_id,
            text="boss appears at north bridge, focus fire in phase 2",
            info={"web": "sample", "guide": "text-only", "datapath": ""},
            image_path=None,
        )
        print(resp)
        _assert_ok(resp, "insert text-only")

        print("[4/8] insert image-only record")
        resp = api.insert_mmr_record(
            instance_id=instance_id,
            text="",
            info={"web": "sample", "guide": "image-only", "datapath": "img://mmr_1"},
            image_path=image_paths[0],
        )
        print(resp)
        _assert_ok(resp, "insert image-only")

        print("[5/8] insert text+image record")
        resp = api.insert_mmr_record(
            instance_id=instance_id,
            text="triangle marker indicates safe route after countdown",
            info={"web": "sample", "guide": "hybrid", "datapath": "img://mmr_3"},
            image_path=image_paths[2],
        )
        print(resp)
        _assert_ok(resp, "insert text+image")

        print("[6/8] build instance")
        resp = api.build_mmr(instance_id)
        print(resp)
        _assert_ok(resp, "build_mmr")

        print("[7/8] query by text")
        text_query = "safe route triangle"
        resp = api.query_mmr(instance_id, text=text_query, topk=2, threshold=0.0)
        print(resp)
        _assert_ok(resp, "query_mmr text")
        if not resp.get("data"):
            raise RuntimeError(f"query_mmr text returns empty data: {resp}")

        print("[8/8] query by image")
        resp = api.query_mmr(instance_id, text="", image_path=image_paths[0], topk=2, threshold=0.0)
        print(resp)
        _assert_ok(resp, "query_mmr image")
        if not resp.get("data"):
            raise RuntimeError(f"query_mmr image returns empty data: {resp}")

        print("List instances")
        print(api.list_mmr_instances())

        print("List records")
        records_resp = api.list_mmr_records(instance_id)
        print(records_resp)
        if records_resp.get("code") != "ok":
            raise RuntimeError(f"list_mmr_records failed: {records_resp}")

        print("Sample finished")
    finally:
        print("Cleanup: delete instance")
        cleanup_resp = api.delete_mmr(instance_id)
        print(cleanup_resp)


if __name__ == "__main__":
    run_sample()
