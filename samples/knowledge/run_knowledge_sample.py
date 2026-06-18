"""
Knowledge service sample script.

This sample reuses existing texts under sample_texts/:
- sample_1.txt
- sample_2.txt

Before running:
- Ensure knowledge service is up.
- Adjust HOST in knowledge_api.py if needed.

Flow:
1. list instances and clean same instance if it exists
2. init instance
3. insert 2 texts into one knowledge base
4. build
5. query with texts_id filters
6. cleanup instance
"""

from __future__ import annotations

import time
from pathlib import Path

from knowledge_api import (
    build_knowledge,
    delete_knowledge,
    init_knowledge,
    insert_knowledge,
    list_knowledge_instances,
    query_knowledge,
)

def run_sample() -> None:
    script_dir = Path(__file__).resolve().parent
    sample_dir = script_dir / "sample_texts"

    text_1 = sample_dir / "sample_1.txt"
    text_2 = sample_dir / "sample_2.txt"

    if not text_1.exists() or not text_2.exists():
        raise FileNotFoundError(
            f"sample texts are required: {text_1} and {text_2}"
        )

    instance_id = f"sample_inst_{int(time.time())}"
    knowledge_id = "sample_knowledge"

    text_files = [str(text_1), str(text_2)]
    text_ids = ["sample_text_1", "sample_text_2"]

    print("[1/6] list_knowledge_instances")
    resp_data = list_knowledge_instances()
    print(resp_data)

    existing_instances = resp_data.get("data", {}).get("instances_id", [])
    if instance_id in existing_instances:
        cleanup = delete_knowledge(instance_id)
        print(cleanup)

    try:
        print("[2/6] init_knowledge")
        resp_data = init_knowledge(instance_id)
        print(resp_data)

        print("[3/6] insert_knowledge")
        resp_data = insert_knowledge(instance_id, knowledge_id, text_files, text_ids)
        print(resp_data)

        print("[4/6] build_knowledge")
        resp_data = build_knowledge(instance_id)
        print(resp_data)
        if resp_data is None:
            raise RuntimeError("build_knowledge returns None")

        print("[5/6] query text 1 with texts_id filter")
        resp_data, resp_message, first_resp_data = query_knowledge(
            instance_id,
            "Who is Elias?",
            texts_id=["sample_text_1"]
        )
        print(f"last_resp_data: {resp_data}")
        print(f"first_resp_data: {first_resp_data}")
        print(f"resp_message: {resp_message}")

        print("[6/6] query text 2 with texts_id filter")
        resp_data, resp_message, first_resp_data = query_knowledge(
            instance_id,
            "林深在做什么？",
            texts_id=["sample_text_2"]
        )
        print(f"last_resp_data: {resp_data}")
        print(f"first_resp_data: {first_resp_data}")
        print(f"resp_message: {resp_message}")

        print("Sample finished")
    finally:
        print("Cleanup: delete_knowledge")
        resp_data = delete_knowledge(instance_id)
        print(resp_data)


if __name__ == "__main__":
    run_sample()
