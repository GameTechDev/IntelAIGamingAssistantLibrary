from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_WALKTHROUGH_DIR = Path(__file__).resolve().parent.parent / "walkthrough"


def _safe_game_dir_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    return cleaned or "unknown_game"


def _run_command(command: list[str], cwd: Path) -> int:
    print(f"[run] {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    return int(completed.returncode)


def _resolve_output_dir(repo_root: Path, raw_output_dir: str) -> Path:
    output_dir = Path(raw_output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    return output_dir.resolve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run walkthrough download then import into the helper service.")
    parser.add_argument("game_name", help="Resolved game name to download and import")
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_WALKTHROUGH_DIR.as_posix(),
        help="Walkthrough output root, default: <script_dir>/walkthrough",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1:9190",
        help="Walkthrough service host, default: 127.0.0.1:9190",
    )
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=20,
        help="Downloader HTTP timeout in seconds, default: 20",
    )
    parser.add_argument(
        "--import-timeout",
        type=float,
        default=30.0,
        help="Importer request timeout in seconds, default: 30",
    )
    parser.add_argument(
        "--force-reimport",
        action="store_true",
        help="Delete existing matching records before import",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed importer logs",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    game_name = str(args.game_name).strip()
    if not game_name:
        print("error: game_name cannot be empty", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parent
    output_dir = _resolve_output_dir(repo_root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    downloader_script = repo_root / "game_walkthrough_downloader.py"
    importer_script = repo_root / "walkthrough_service_importer.py"
    json_path = output_dir / _safe_game_dir_name(game_name) / "text_images.json"

    download_command = [
        sys.executable,
        str(downloader_script),
        game_name,
        str(output_dir),
        "--timeout",
        str(args.download_timeout),
    ]
    download_code = _run_command(download_command, cwd=repo_root)
    if download_code != 0:
        return download_code

    if not json_path.exists():
        print(f"error: downloaded walkthrough json not found: {json_path}", file=sys.stderr)
        return 2

    import_command = [
        sys.executable,
        str(importer_script),
        str(json_path),
        "--instance-id",
        game_name,
        "--host",
        str(args.host),
        "--timeout",
        str(args.import_timeout),
    ]
    if args.force_reimport:
        import_command.append("--force-reimport")
    if args.verbose:
        import_command.append("--verbose")

    return _run_command(import_command, cwd=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())