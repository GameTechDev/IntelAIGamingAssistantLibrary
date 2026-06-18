from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def append_detected_process(process: str, game_name: str) -> Path:
    """Append or update process -> game_name mapping in ../detected_processes.json."""
    process_name = str(process).strip()
    resolved_game_name = str(game_name).strip()

    if not process_name:
        raise ValueError("process cannot be empty")
    if not resolved_game_name:
        raise ValueError("game_name cannot be empty")

    script_dir = Path(__file__).resolve().parent
    json_path = script_dir.parent / "detected_processes.json"

    if not json_path.exists():
        data: dict[str, Any] = {}
    else:
        try:
            with json_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
        except json.JSONDecodeError:
            loaded = {}

        if isinstance(loaded, dict):
            data = loaded
        else:
            data = {}

    data[process_name] = resolved_game_name

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return json_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append process -> game_name to ../detected_processes.json"
    )
    parser.add_argument("process", help="Process name, e.g. game.exe")
    parser.add_argument("game_name", help="Game name mapped to the process")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    path = append_detected_process(args.process, args.game_name)
    print(f"updated: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
