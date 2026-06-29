[English](./README.md) | 简体中文

## 中文说明

**Intel® AI Gaming Assistant Library** 是一个运行在本地的 AI 推理后端服务，为游戏提供截图理解、多模态检索、知识库问答和记忆管理等智能辅助能力。所有推理均在本地完成，充分利用 Intel GPU 和 NPU 加速。

### 主要功能

- **Vision（视觉）** — 截图场景识别与图像检索
- **Knowledge Base（知识库）** — 基于 RAG 的知识问答（Embedding + Rerank + LLM）
- **Memory（记忆）** — 持久化对话记忆管理
- **MMR（多模态检索）** — 结合视觉与语义的多模态检索

服务默认监听 `127.0.0.1:9190`，通过 HTTP API 与客户端集成。

### 系统要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 64位 |
| CPU | Intel® Core™ Ultra 系列处理器（推荐） |
| GPU | Intel® Arc™ 独显 或 Intel® Core™ Ultra 核显 |
| NPU | Intel® NPU（用于视觉模型加速） |
| 内存 | 最低 16 GB，推荐 32 GB |
| 磁盘 | 20 GB 可用空间 |

> **注意：** 本发布包**不包含** LLM、Embedding 和 Rerank 模型。请参考下方 [快速开始](#快速开始) 完成模型下载与放置。

## 快速开始

### 0. 下载游戏助手服务

从[Releases](https://github.com/GameTechDev/IntelAIGamingAssistantLibrary/releases)页面下载最新的`GameAssistantToolServer.7z`。

下载完成后，解压`GameAssistantToolServer.7z`。

> **注意：** 建议将游戏助手服务解压至根目录或名字较短的目录中，例如`D:\`或`D:\apps\`。
>
> 这是因为游戏助手服务在存储一些文件时会以MD5或SHA256命名文件，若文件的完整路径超过了Windows的260字符的限制，会导致文件读取失败。
>
> 您也可以通过修改`config\gameassistanttoolserver.json`里的`saves`来指定数据要保存的目录。

### 1. 模型准备

模型文件需放置在可执行文件同目录下的 `models\` 文件夹中：

| 路径 | 说明 |
|------|------|
| `models\llm` | 对话 LLM — OpenVINO IR 格式 |
| `models\emb` | 文本向量模型 — OpenVINO IR 格式 |
| `models\rerank` | 重排序模型 — OpenVINO IR 格式 |
| `models\splitter` | 文本分块模型 |
| `models\mmr` | 多模态向量模型 — OpenVINO IR 格式 |

LLM、Embedding 和 Rerank 模型与具体实现解耦，支持任意兼容的 OpenVINO IR 格式模型。可在 [Hugging Face OpenVINO 社区](https://huggingface.co/OpenVINO) 获取已转换好的模型，或使用 [Optimum-Intel](https://github.com/huggingface/optimum-intel) 自行转换。

Splitter模型可以去 [Spacy官网](https://spacy.io/models/) 下载对应语言的模型。

MMR 默认从 `models\mmr\gme` 加载（由 `config\mmr.json` 中的 `mmr.gme.model_path` 配置）。模型可从 [Hugging Face Alibaba-NLP 社区](https://huggingface.co/Alibaba-NLP/gme-Qwen2-VL-7B-Instruct)下载，然后使用[Optimum-Intel](https://github.com/huggingface/optimum-intel) 自行转换。


此外，我们在 [`demo/dowload_models`](./demo/dowload_models) 目录下提供了从 ModelScope 下载并整理模型的脚本与说明，便于个人本地体验和验证。需要说明的是，这些通过脚本下载的模型不属于游戏助手服务发布内容的一部分，其使用需遵循对应模型的许可约束；当前仅限个人使用，不可用于商业用途。


### 2. 运行

双击`GameAssistantToolServer`目录中的`GameAssistantToolServer.exe`即可启动服务。

服务默认启动于 `127.0.0.1:9190`。如需修改监听地址或端口，请编辑 `config\gameassistanttoolserver.json`。

### 3. 运行验证

服务启动后，日志会显示各组件的初始化状态。你可以向以下地址发送请求：

```
http://127.0.0.1:9190
```

## 配置说明

所有配置文件位于 `config\` 目录：

| 文件 | 说明 |
|------|------|
| `gameassistanttoolserver.json` | 主服务配置（主机、端口、模型路径、功能开关） |
| `memory.json` | 记忆服务配置 |
| `mmr.json` | MMR 服务配置 |
| `runtime.json` | 运行时行为配置 |
| `logger.json` | 日志配置 |

更详细的配置项与接口说明请参阅 `docs\` 目录。

## API 参考

完整 API 文档位于 `docs\` 目录，建议重点阅读：

- **接口说明** — 各功能 HTTP API 端点说明
- **配置文件说明** — 全部配置字段详解

## 许可证

本软件采用 [Intel OBL Tools License Agreement](./license/) 许可。

开源组件及其许可证信息见 [third-party-programs.txt](./third-party-programs.txt)。

## 安全

如发现安全漏洞，请遵循 Intel 的安全报告流程。详情见 [SECURITY.md](./SECURITY.md)。

---

