English | [简体中文](./README_CN.md)

# Model Download Script Guide

> This script is for demonstration purposes only. It is for personal use only and must not be used for commercial purposes.

## What it does

Downloads the following models from ModelScope, then moves and renames them under `models\`:

- `DeviLeo/Qwen3-4B-int4-ov` -> `models\llm`
- `DeviLeo/bge-m3-int4-sym-ov` -> `models\embedding`
- `DeviLeo/bge-reranker-v2-m3-int4-sym-ov` -> `models\reranker`
- `DeviLeo/gme-Qwen2-VL-2B-Instruct-int4-sym-ov` -> `models\mmr\gme`
- One splitter model (choose one):
  - `DeviLeo/zh_core_web_sm-3.8.0` -> `models\splitter`
  - `DeviLeo/en_core_web_sm-3.8.0` -> `models\splitter`

## Prerequisites

1. Python 3.9+  
2. Install ModelScope SDK:

```powershell
pip install modelscope
```

## Usage

Run from the repository root:

```powershell
python .\tools\download_modelscope_models.py
```

If `--splitter` is not provided, the script will prompt you to choose `zh` or `en`.

Specify the splitter directly:

```powershell
python .\tools\download_modelscope_models.py --splitter zh
python .\tools\download_modelscope_models.py --splitter en
```

If you run it outside the repo root, pass `--root`:

```powershell
python .\tools\download_modelscope_models.py --root "C:\path\to\IntelAIGamingAssistantLibrary" --splitter zh
```

## Notes

- Existing target model folders (for example `models\llm`, `models\splitter`) will be overwritten.
- The script creates a temporary folder `_modelscope_download_tmp` and cleans it up automatically.
