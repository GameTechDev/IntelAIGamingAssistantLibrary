"""
Memory service sample script.

What this sample demonstrates:
1. Generate 6 local demo images.
2. Init memory instance.
3. Insert several records with properties/tags/emb_props/images.
4. Build instance index.
5. Search by conditions, text, and image.
6. List records and cleanup.

Before running:
- Ensure memory service is up.
- Adjust HOST in memory_api.py if needed.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

import memory_api as api

def generate_demo_images(output_dir: Path) -> list[str]:
    """Create at least 6 synthetic images for image search demo."""
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("mem_1", "#FDEDEC", "#C0392B", "circle"),
        ("mem_2", "#EAF2F8", "#2980B9", "rect"),
        ("mem_3", "#E8F8F5", "#16A085", "triangle"),
        ("mem_4", "#FEF9E7", "#B7950B", "cross"),
        ("mem_5", "#F5EEF8", "#8E44AD", "diamond"),
        ("mem_6", "#F4F6F7", "#2C3E50", "bars"),
    ]

    w, h = 640, 360
    image_paths: list[str] = []

    for name, bg, fg, shape in specs:
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        if shape == "circle":
            draw.ellipse((180, 70, 460, 350), fill=fg, outline="#7B241C", width=8)
        elif shape == "rect":
            draw.rounded_rectangle((120, 80, 520, 300), radius=28, fill=fg, outline="#1F618D", width=8)
        elif shape == "triangle":
            draw.polygon([(320, 60), (120, 300), (520, 300)], fill=fg, outline="#0E6655", width=8)
        elif shape == "cross":
            draw.line((130, 90, 510, 290), fill=fg, width=22)
            draw.line((510, 90, 130, 290), fill=fg, width=22)
            draw.rectangle((90, 50, 550, 320), outline="#7D6608", width=8)
        elif shape == "diamond":
            draw.polygon([(320, 40), (540, 180), (320, 320), (100, 180)], fill=fg, outline="#5B2C6F", width=8)
        else:
            for i in range(8):
                x0 = 80 + i * 60
                x1 = x0 + 36
                y0 = 60 + (i % 2) * 30
                y1 = 320 - (i % 2) * 30
                draw.rectangle((x0, y0, x1, y1), fill=fg)
            draw.rectangle((60, 40, 580, 330), outline="#1B2631", width=8)

        draw.text((20, 20), f"Memory Sample Image: {name}", fill="#111111")

        file_path = output_dir / f"{name}.png"
        img.save(file_path)
        image_paths.append(str(file_path))

    return image_paths


def build_demo_records(image_paths: list[str]) -> list[dict]:
    records = []
    for i in range(6):
        records.append(
            {
                "record_id": f"record_{i}",
                "info": {
                    "datetime": f"2026-03-19 10:0{i}:00",
                    "event": f"成功_{i}" if i % 2 == 0 else f"失败_{i}",
                    "kill": i,
                    "defeat": max(0, 5 - i),
                    "assistant": i % 3,
                    "round": i + 1,
                    "location": f"基地_{i}" if i % 2 == 0 else f"太空_{i}",
                    "weapon": f"物理学圣剑_{i}" if i % 2 == 0 else f"撬棍_{i}",
                    "money": 3000 + i * 1200
                },
                "tags": ["event", f"tag_{i % 3}", f"index_{i}"],
                "emb_props": ["event", "location"],
                "images": [image_paths[i], image_paths[(i - 1) % len(image_paths)]],
            }
        )
    return records


def run_sample() -> None:
    ts = int(time.time())
    instance_id = f"sample_memory_inst_{ts}"

    script_dir = Path(__file__).resolve().parent
    image_dir = script_dir / "sample_images"
    image_paths = generate_demo_images(image_dir)
    records = build_demo_records(image_paths)

    print("[1/8] init instance")
    resp = api.init_instance(instance_id)
    print(resp)

    try:
        print("[2/8] insert records")
        for rec in records:
            resp = api.insert_record(
                instance_id,
                rec["record_id"],
                rec["info"],
                rec["tags"],
                rec["emb_props"],
                rec["images"],
            )
            print(f"insert {rec['record_id']} -> {resp}")

        print("[3/8] list records")
        resp = api.list_record(instance_id)
        print(resp)

        print("[4/8] build instance")
        resp = api.build_instance(instance_id)
        print(resp)

        print("[5/8] condition search")
        conditions = [
            {"key": "kill", "value": 2, "op": ">=", "set_op": "&&"},
            {"key": "money", "value": 4500, "op": ">=", "set_op": "&&"},
        ]
        resp = api.search_instance(instance_id, conditions, tags=["event"], tags_op="&&")
        found_records = [ record['record_id'] for record in resp.get('data', {}).get('records', []) ]
        print(f"found records: {found_records}")

        print("[6/8] text search")
        resp = api.search_text(instance_id, "成功", topk=5, threshold=0.3, tags=["event"], tags_op="&&")
        found_records = [ record['record_id'] for record in resp.get('data', {}).get('records', []) ]
        print(f"found records: {found_records}")

        print("[7/8] image search")
        query_image = image_paths[0]
        resp = api.search_image(
            instance_id,
            query_image,
            topk=5,
            threshold=0.5,
            threshold_2=0.05,
            tags=["event"],
            tags_op="&&",
            return_image_data=False,
        )
        print(resp)
        
        expected_record_ids = [ records[0]["record_id"], records[1]["record_id"] ]
        actual_record_id = resp.get("data", {}).get("records", [])[0].get("record_id")
        if actual_record_id not in expected_record_ids:
            raise RuntimeError(
                f"unexpected top1 record_id for {query_image}, expected={expected_record_ids}, actual={actual_record_id}"
            )

        print("[8/8] filtered list with keys/props")
        resp = api.list_record(
            instance_id,
            indices=[0, 2, 4],
            tags=["event"],
            tags_op="&&",
            keys=["record_id", "properties", "tags"],
            props=["event", "kill", "money"],
            return_image_data=False,
        )
        print(resp)

        print("Sample finished")
    finally:
        print("Cleanup: delete instance")
        cleanup = api.delete_instance(instance_id)
        print(cleanup)


if __name__ == "__main__":
    run_sample()
