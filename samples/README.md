# Samples README

English | [简体中文](./README_CN.md)

This directory contains runnable client examples for the local GameAssistantToolServer HTTP APIs.

## Directory Overview

- `knowledge/`: Knowledge service sample (insert/build/query text knowledge).
- `memory/`: Memory service sample (insert/build/search structured records with images).
- `mmr/`: MMR service sample (multimodal insert/query by text and image).
- `vision/`: Vision service sample (scene image insert/build/query).
- `requirements.txt`: Python dependencies for all sample scripts.

## Prerequisites

1. Start GameAssistantToolServer first (default host: `127.0.0.1:9190`).
2. Ensure required models are prepared according to the root README.
3. Use Python 3.10+ (recommended).

## Install Sample Dependencies

From this directory:

```bat
cd samples
pip install -r requirements.txt
```

Dependencies in `requirements.txt`:

- `rich`
- `requests-toolbelt`
- `pillow`

## Run Samples

Run commands from `samples`:

### 1) Knowledge Sample

```bat
cd knowledge
python run_knowledge_sample.py
```

What it does:

1. Uses `sample_texts/sample_1.txt` and `sample_texts/sample_2.txt`.
2. Initializes one knowledge instance.
3. Inserts text files and builds index.
4. Queries twice.
5. Cleans up instance.

### 2) Memory Sample

```bat
cd memory
python run_memory_sample.py
```

What it does:

1. Generates demo images under `memory/sample_images`.
2. Initializes one memory instance.
3. Inserts records with properties/tags/images.
4. Builds index.
5. Runs condition, text, and image search.
6. Validates top-1 image result and cleans up.

### 3) MMR Sample

```bat
cd mmr
python run_mmr_sample.py
```

What it does:

1. Generates demo images under `mmr/sample_images`.
2. Checks MMR enable state.
3. Initializes one MMR instance.
4. Inserts text-only, image-only, and hybrid records.
5. Builds index.
6. Queries by text and image.
7. Lists records and cleans up.

### 4) Vision Sample

```bat
cd vision
python run_vision_sample.py
```

What it does:

1. Generates demo images under `vision/sample_images`.
2. Initializes one vision instance and inserts scene pictures.
3. Builds index.
4. Queries with the same images.
5. Verifies top-1 picture id matches expectation.
6. Cleans up instance.

## Host and Port

All APIs default to:

- `HOST = "127.0.0.1:9190"`

If your server runs elsewhere, edit these files:

- `knowledge/knowledge_api.py`
- `memory/memory_api.py`
- `mmr/mmr_api.py`
- `vision/vision_api.py`

## Expected Result

A successful run usually shows:

- API responses with `"code": "ok"`
- progress output for build/query stages
- final cleanup request success

## Troubleshooting

- Connection errors: confirm server is running and reachable on the configured host.
- Build/query failures: check server logs and model/config readiness.
- Missing packages: re-run `pip install -r requirements.txt`.
- Permission/file errors: run from the corresponding sample directory so relative paths resolve correctly.
