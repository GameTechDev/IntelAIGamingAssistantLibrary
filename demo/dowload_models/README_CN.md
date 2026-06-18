[English](./README.md) | 简体中文

# 模型下载脚本使用说明

## 功能

从 ModelScope 下载以下模型，并自动移动到项目 `models\` 目录并重命名：

- `DeviLeo/Qwen3-4B-int4-ov` -> `models\llm`
- `DeviLeo/bge-m3-int4-sym-ov` -> `models\embedding`
- `DeviLeo/bge-reranker-v2-m3-int4-sym-ov` -> `models\reranker`
- `DeviLeo/gme-Qwen2-VL-2B-Instruct-int4-sym-ov` -> `models\mmr\gme`
- 分词模型二选一：
  - `DeviLeo/zh_core_web_sm-3.8.0` -> `models\splitter`
  - `DeviLeo/en_core_web_sm-3.8.0` -> `models\splitter`

## 前置条件

1. 安装 Python 3.9+  
2. 安装 ModelScope SDK：

```powershell
pip install modelscope
```

## 用法

在仓库根目录执行：

```powershell
python .\tools\download_modelscope_models.py
```

不传 `--splitter` 时，会交互选择 `zh` 或 `en` 分词模型。

可直接指定分词模型：

```powershell
python .\tools\download_modelscope_models.py --splitter zh
python .\tools\download_modelscope_models.py --splitter en
```

如果脚本不是在仓库根目录运行，可指定项目根目录：

```powershell
python .\tools\download_modelscope_models.py --root "C:\path\to\IntelAIGamingAssistantLibrary" --splitter zh
```

## 注意事项

- 脚本会覆盖目标目录中已存在的同名模型目录（如 `models\llm`、`models\splitter`）。
- 下载过程中会创建临时目录 `_modelscope_download_tmp`，脚本结束后自动清理。
