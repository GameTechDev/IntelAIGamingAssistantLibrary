from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import sys
from queue import Empty
from pathlib import Path

try:
    from modelscope.hub.snapshot_download import snapshot_download
except Exception:
    snapshot_download = None


COMMON_MODELS = {
    "DeviLeo/Qwen3-4B-int4-ov": ("models", "llm"),
    "DeviLeo/bge-m3-int4-sym-ov": ("models", "emb"),
    "DeviLeo/bge-reranker-v2-m3-int4-sym-ov": ("models", "rerank"),
    "DeviLeo/gme-Qwen2-VL-2B-Instruct-int4-sym-ov": ("models", "mmr", "gme"),
}

SPLITTER_MODELS = {
    "zh": ("DeviLeo/zh_core_web_sm-3.8.0", ("models", "splitter")),
    "en": ("DeviLeo/en_core_web_sm-3.8.0", ("models", "splitter")),
}

MESSAGES = {
    "zh": {
        "script_description": "从 ModelScope 下载 DeviLeo 模型并放置到 models\\ 目录。",
        "lang_prompt": "请选择脚本语言:",
        "lang_choice_zh": "1) 中文",
        "lang_choice_en": "2) English",
        "lang_input": "输入 1 或 2: ",
        "lang_invalid": "输入无效，请重试。",
        "splitter_help": "选择分词模型：zh 或 en。如果不提供，则会交互式询问。",
        "root_help": "项目根目录。models\\ 会创建在该目录下。默认：当前目录。",
        "choose_splitter": "请选择分词模型:",
        "splitter_choice_zh": "1) zh_core_web_sm-3.8.0",
        "splitter_choice_en": "2) en_core_web_sm-3.8.0",
        "missing_sdk": "未找到 modelscope SDK，请先安装: pip install modelscope",
        "download_start": "开始下载模型...",
        "downloading": "下载:",
        "download_done": "下载完成，开始移动并重命名...",
        "installed": "已安装:",
        "all_done": "全部完成。",
        "cancelled": "已取消下载。",
        "download_failed": "下载失败:",
    },
    "en": {
        "script_description": "Download DeviLeo models from ModelScope and place them under models\\.",
        "lang_prompt": "Choose script language:",
        "lang_choice_zh": "1) 中文",
        "lang_choice_en": "2) English",
        "lang_input": "Enter 1 or 2: ",
        "lang_invalid": "Invalid input. Please try again.",
        "splitter_help": "Choose splitter model: zh or en. If omitted, asks interactively.",
        "root_help": "Project root path. models\\ will be created under this path. Default: current directory.",
        "choose_splitter": "Choose splitter model:",
        "splitter_choice_zh": "1) zh_core_web_sm-3.8.0",
        "splitter_choice_en": "2) en_core_web_sm-3.8.0",
        "missing_sdk": "ModelScope SDK not found. Install it first: pip install modelscope",
        "download_start": "Starting model download...",
        "downloading": "Downloading:",
        "download_done": "Download finished. Moving and renaming...",
        "installed": "Installed:",
        "all_done": "Done.",
        "cancelled": "Download cancelled.",
        "download_failed": "Download failed:",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download DeviLeo models from ModelScope and place them under models\\."
    )
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        help="Script language. If omitted, asks interactively at startup.",
    )
    parser.add_argument(
        "--splitter",
        choices=["zh", "en"],
        help="Choose splitter model: zh or en. If omitted, asks interactively.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Project root path. models\\ will be created under this path. Default: current directory.",
    )
    return parser.parse_args()


def tr(lang: str, key: str) -> str:
    return MESSAGES[lang][key]


def choose_language(lang_arg: str | None) -> str:
    if lang_arg in {"zh", "en"}:
        return lang_arg

    while True:
        print("请选择脚本语言 / Choose script language:")
        print("1) 中文")
        print("2) English")
        choice = input("输入 1 或 2 / Enter 1 or 2: ").strip()
        if choice == "1":
            return "zh"
        if choice == "2":
            return "en"
        print("输入无效，请重试。 / Invalid input. Please try again.")


def choose_splitter(lang: str, splitter_arg: str | None) -> str:
    if splitter_arg in {"zh", "en"}:
        return splitter_arg

    while True:
        print(tr(lang, "choose_splitter"))
        print(tr(lang, "splitter_choice_zh"))
        print(tr(lang, "splitter_choice_en"))
        choice = input(tr(lang, "lang_input")).strip()
        if choice == "1":
            return "zh"
        if choice == "2":
            return "en"
        print(tr(lang, "lang_invalid"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def install_model(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


def _download_worker(repo_id: str, cache_dir: str, result_queue: mp.Queue) -> None:
    try:
        if snapshot_download is None:
            result_queue.put(("error", "modelscope SDK not available in worker process"))
            return
        local_path = snapshot_download(repo_id, cache_dir=cache_dir)
        result_queue.put(("ok", str(local_path)))
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(("error", repr(exc)))


def download_with_interrupt(repo_id: str, cache_dir: Path) -> Path:
    result_queue: mp.Queue = mp.Queue()
    proc = mp.Process(
        target=_download_worker,
        args=(repo_id, str(cache_dir), result_queue),
        daemon=False,
    )
    proc.start()

    try:
        while proc.is_alive():
            proc.join(timeout=0.2)
    except KeyboardInterrupt:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2)
        raise

    if proc.exitcode is None:
        raise RuntimeError("download process ended unexpectedly")

    try:
        status, payload = result_queue.get_nowait()
    except Empty:
        if proc.exitcode == 0:
            raise RuntimeError("download process returned no result")
        raise RuntimeError(f"download process exited with code {proc.exitcode}")

    if status != "ok":
        raise RuntimeError(payload)
    return Path(payload).resolve()


def main() -> int:
    args = parse_args()
    lang = choose_language(args.lang)

    if snapshot_download is None:
        print(tr(lang, "missing_sdk"), file=sys.stderr)
        return 1

    try:
        splitter_key = choose_splitter(lang, args.splitter)
        splitter_repo, splitter_dest_parts = SPLITTER_MODELS[splitter_key]

        project_root = Path(args.root).resolve()
        cache_root = project_root / "_modelscope_download_cache"
        ensure_dir(cache_root)

        planned = dict(COMMON_MODELS)
        planned[splitter_repo] = splitter_dest_parts

        downloaded_paths: dict[str, Path] = {}
        try:
            print(tr(lang, "download_start"))
            for repo_id in planned:
                print(f'{tr(lang, "downloading")} {repo_id}')
                downloaded_paths[repo_id] = download_with_interrupt(repo_id, cache_root)

            print(tr(lang, "download_done"))
            for repo_id, dest_parts in planned.items():
                src = downloaded_paths[repo_id]
                dest = project_root.joinpath(*dest_parts)
                install_model(src, dest)
                print(f'{tr(lang, "installed")} {repo_id} -> {dest}')

            print(tr(lang, "all_done"))
            return 0
        except RuntimeError as exc:
            print(f'{tr(lang, "download_failed")} {exc}', file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        print(f"\n{tr(lang, 'cancelled')}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
