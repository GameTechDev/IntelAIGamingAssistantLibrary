English | [简体中文](./README_CN.md)

# Intel® AI Gaming Assistant Library

Intel® AI Gaming Assistant Library is an AI-powered local backend service that enables in-game intelligent assistance features, including screenshot understanding, multimodal retrieval, knowledge base Q&A, and memory management. It runs entirely on-device, leveraging Intel GPU and NPU for accelerated inference.

## What's Inside?

- **Vision** — Screenshot-based scene recognition and image retrieval
- **Knowledge Base** — RAG pipeline with embedding, reranking, and LLM-based Q&A
- **Memory** — Persistent conversation memory management
- **MMR** — Multimodal retrieval combining vision and semantic search

The server exposes a local HTTP API (default port `9190`) for client integration.

## System Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Windows 10/11 64-bit |
| CPU | Intel® Core™ Ultra processor (recommended) |
| GPU | Intel® Arc™ dGPU or Intel® Core™ Ultra integrated GPU |
| NPU | Intel® NPU (for vision models) |
| RAM | 16 GB minimum, 32 GB recommended |
| Disk | 20 GB free space |

> **Note:** The LLM, embedding and rerank models are **not bundled** in this release. See [Getting Started](#getting-started) for model download instructions.

## Getting Started

### 0. Download GameAssistantToolServer

Download the newest `GameAssistantToolServer.7z` package from the [Releases](https://github.com/GameTechDev/IntelAIGamingAssistantLibrary/releases) page.

Once the download is complete, extract the archive `GameAssistantToolServer.7z`.

### 1. Download Models

The following model directories must be placed under the `models\` folder alongside the executable:

| Path | Description |
|------|-------------|
| `models\llm` | Chat LLM — OpenVINO IR format |
| `models\emb` | Text embedding model — OpenVINO IR format |
| `models\rerank` | Rerank model — OpenVINO IR format |
| `models\splitter` | Text splitter model |
| `models\mmr` | Multimodal embedding model — OpenVINO IR format |

The LLM, embedding, and rerank models are interchangeable. Any compatible model in OpenVINO IR format can be used. Pre-converted models are available on the [OpenVINO community on Hugging Face](https://huggingface.co/OpenVINO). You can also convert models yourself using [Optimum-Intel](https://github.com/huggingface/optimum-intel).

For the splitter model, you can download the language-specific package from the [spaCy model catalog](https://spacy.io/models/).

For MMR, the default configuration loads from `models\mmr\gme` (configured by `config\mmr.json`, field `mmr.gme.model_path`). You can download the model from [Alibaba-NLP on Hugging Face](https://huggingface.co/Alibaba-NLP/gme-Qwen2-VL-7B-Instruct) and convert the model using [Optimum-Intel](https://github.com/huggingface/optimum-intel).

In addition, we provide scripts and instructions under [`demo/dowload_models`](./demo/dowload_models) to download and arrange models from ModelScope for local personal evaluation and validation. These downloaded models are not part of the Game Assistant service release itself, and their use is subject to the applicable model licenses. At present, they are for personal use only and may not be used for commercial purposes.

### 2. Run the Server

Double-click `GameAssistantToolServer.exe` in `GameAssistantToolServer` folder to start the service.

The server starts on `127.0.0.1:9190` by default. See `config\gameassistanttoolserver.json` to change the host or port.

### 3. Verify

Once started, the server log will confirm each component's initialization status. You can send requests to:

```
http://127.0.0.1:9190
```

## Configuration

All configuration files are located in the `config\` folder:

| File | Description |
|------|-------------|
| `gameassistanttoolserver.json` | Main server config (host, port, model paths, feature toggles) |
| `memory.json` | Memory service configuration |
| `mmr.json` | MMR service configuration |
| `runtime.json` | Runtime behavior settings |
| `logger.json` | Logging configuration |

See the `docs\` folder for detailed configuration and API reference documentation.

## API Reference

Full API documentation is available in the `docs\` folder. Refer to the following guides:

- **Interface Reference** — HTTP API endpoints for all features
- **Configuration Guide** — Detailed explanation of all config fields

## License

This software is licensed under the [Intel OBL Tools License Agreement](./license/).

See [third-party-programs.txt](./third-party-programs.txt) for open source components and their licenses.

## Security

Please report security vulnerabilities following Intel's guidelines. See [SECURITY.md](./SECURITY.md) for details.

---
