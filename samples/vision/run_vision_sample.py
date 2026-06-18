"""
Vision service sample script.

What this script does:
1. Generates 4 synthetic demo images locally.
2. Creates a vision instance and inserts those images into one scene.
3. Builds the instance index.
4. Queries each generated image and prints top-1 result.
5. Cleans up by deleting the instance.

Before running:
- Ensure vision service is up.
- Set HOST in vision_api.py if needed.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

from vision_api import (
    build_vision,
    delete_vision,
    init_vision,
    insert_vision,
    list_vision_scene_pictures,
    list_vision_scenes,
    query_vision,
)


def generate_demo_images(output_dir: Path) -> list[str]:
    """Generate at least 4 synthetic images that can be used for vision matching."""
    output_dir.mkdir(parents=True, exist_ok=True)

    width, height = 640, 360
    image_paths: list[str] = []

    # Different geometry/color combinations make them easy to distinguish.
    specs = [
        ("demo_pic_1", "#EAF6FF", "#1E88E5", "circle"),
        ("demo_pic_2", "#FFF8E1", "#F4511E", "rectangle"),
        ("demo_pic_3", "#E8F5E9", "#43A047", "triangle"),
        ("demo_pic_4", "#FCE4EC", "#8E24AA", "cross"),
    ]

    for name, bg, fg, shape in specs:
        img = Image.new("RGB", (width, height), color=bg)
        draw = ImageDraw.Draw(img)

        if shape == "circle":
            draw.ellipse((180, 70, 460, 350), fill=fg, outline="#0D47A1", width=8)
        elif shape == "rectangle":
            draw.rounded_rectangle((120, 80, 520, 300), radius=32, fill=fg, outline="#BF360C", width=8)
        elif shape == "triangle":
            draw.polygon([(320, 60), (120, 300), (520, 300)], fill=fg, outline="#1B5E20", width=8)
        else:
            draw.line((120, 80, 520, 300), fill=fg, width=22)
            draw.line((520, 80, 120, 300), fill=fg, width=22)
            draw.rectangle((80, 40, 560, 320), outline="#4A148C", width=8)

        draw.text((20, 20), f"Vision Sample: {name}", fill="#111111")

        file_path = output_dir / f"{name}.png"
        img.save(file_path)
        image_paths.append(str(file_path))

    return image_paths


def run_sample() -> None:
    timestamp = int(time.time())
    instance_id = f"sample_inst_{timestamp}"
    scene_id = "sample_scene"

    script_dir = Path(__file__).resolve().parent
    image_dir = script_dir / "sample_images"

    image_paths = generate_demo_images(image_dir)
    picture_ids = [f"sample_pic_{i + 1}" for i in range(len(image_paths))]

    print("[1/6] init instance")
    resp = init_vision(instance_id)
    print(resp)
    if resp.get("code") != "ok":
        raise RuntimeError(f"init_vision failed: {resp}")

    try:
        print("[2/6] insert images")
        resp = insert_vision(instance_id, scene_id, image_paths, picture_ids, mode="accurate")
        print(resp)
        if resp.get("code") != "ok":
            raise RuntimeError(f"insert_vision failed: {resp}")

        print("[3/6] build")
        resp = build_vision(instance_id)
        print(resp)
        if resp is None or resp.get("code") != "ok":
            raise RuntimeError(f"build_vision failed: {resp}")

        print("[4/6] list scenes")
        resp = list_vision_scenes(instance_id)
        print(resp)

        print("[5/6] list scene pictures")
        resp = list_vision_scene_pictures(instance_id, scene_id)
        print(resp)

        print("[6/6] query with the same images")
        for i, image_path in enumerate(image_paths):
            expected_pic_id = picture_ids[i]
            query_resp = query_vision(instance_id, image_path, topk=1, threshold=0.6, threshold_2=0.1)
            print(f"query[{i + 1}] -> {query_resp}")

            if query_resp.get("code") != "ok":
                raise RuntimeError(f"query_vision failed for {image_path}: {query_resp}")
            
            data = query_resp.get("data", [])
            if not data:
                raise RuntimeError(f"query_vision returns empty data for {image_path}: {query_resp}")

            actual_pic_id = data[0].get("picture_id")
            if actual_pic_id != expected_pic_id:
                raise RuntimeError(
                    f"unexpected top1 picture_id for {image_path}, expected={expected_pic_id}, actual={actual_pic_id}"
                )

        print("Sample finished")
    finally:
        print("Cleanup: delete instance")
        cleanup_resp = delete_vision(instance_id)
        print(cleanup_resp)


if __name__ == "__main__":
    run_sample()
