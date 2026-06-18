from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 1.0


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _run_detection(script_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(script_path.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"game_detection.py failed: code={result.returncode}, stderr={result.stderr.strip()}"
        )

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise RuntimeError("game_detection.py returned empty stdout")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"game_detection.py output is not valid JSON: {stdout}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"game_detection.py output is not a JSON object: {payload}")
    return payload


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    detection_script = repo_root / "game_detection.py"
    if not detection_script.exists():
        print(json.dumps({"status": "error", "message": "game_detection.py not found"}, ensure_ascii=False))
        return 1

    latest: dict[str, Any] | None = None
    attempts = 0
    for attempts in range(1, MAX_RETRIES + 1):
        latest = _run_detection(detection_script)
        process_name = latest.get("process")
        if not _is_blank(process_name):
            break
        if attempts < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    if latest is None:
        print(json.dumps({"status": "error", "message": "no detection result"}, ensure_ascii=False))
        return 1

    process_name = latest.get("process")
    game_name = latest.get("name")

    if _is_blank(process_name):
        print(
            json.dumps(
                {
                    "status": "stop_no_process",
                    "attempts": attempts,
                    "process": None,
                    "name": None,
                    "should_launch_client": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    process_str = str(process_name).strip()
    if _is_blank(game_name):
        print(
            json.dumps(
                {
                    "status": "need_agent_resolve_name",
                    "attempts": attempts,
                    "process": process_str,
                    "name": None,
                    "should_launch_client": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(
        json.dumps(
            {
                "status": "launch_direct",
                "attempts": attempts,
                "process": process_str,
                "name": str(game_name).strip(),
                "should_launch_client": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
