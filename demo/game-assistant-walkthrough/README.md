[English](./README_EN.md) | 简体中文

# 游戏助手路书使用说明

> 此工具仅作演示用途，仅限个人使用，请勿商用。

欢迎使用[游戏助手路书工具](https://github.com/GameTechDev/IntelAIGamingAssistantLibrary/tree/main/demo/game-assistant-walkthrough)。

工具支持两种使用方式：

1. 直接用 Python 脚本运行（本地命令行方式）。
2. 通过 AI智能体（Agentic AI） 调用 Skill 执行（自然语言方式）。

本项目的核心能力包括：

- 检测当前游戏进程（基于 GPU Engine 使用率）。
- 自动下载并整理图文攻略（当前实现基于游民星空页面解析）。
- 将攻略导入游戏助手服务（Knowledge/Vision）。
- 启动桌面攻略客户端浮层，并支持按游戏名直启。

## 0. 前提

使用前确保`游戏助手服务端`已经启动，工具的场景识别功能依赖该服务。

工具默认会连接游戏助手服务地址：`127.0.0.1:9190`。

如果你的服务不在默认地址，请在命令中通过参数指定。

## 1. 目录结构

```text
game-assistant-walkthrough
├─ SKILL.md
├─ README.md
├─ README_EN.md
└─ scripts/
   ├─ append_detected_process.py
   ├─ detect_game_with_retries.py
   ├─ download_and_import_walkthrough.py
   ├─ game_client.py
   ├─ game_detection.py
   ├─ game_walkthrough_downloader.py
   ├─ requirements.txt
   └─ walkthrough_service_importer.py
```

运行后还会在项目目录下动态生成：

- `walkthrough/`：下载的攻略与中间文件。
- `logs/`：`game_client.py` 运行日志。
- `detected_processes.json`：进程名到游戏名映射（由 `append_detected_process.py` 维护）。

## 2. 环境要求

- OS：Windows（当前检测逻辑依赖 Win32/PDH API）。
- Python：建议 3.10+。

安装依赖：

```powershell
python -m pip install -r .\scripts\requirements.txt
```

`tkinter` 通常随 Windows Python 自带；如你使用精简版 Python 发行包，请确认 tkinter 可用。

## 3. Python 方式使用

以下命令在项目根目录执行。

### 3.1 启动攻略客户端（自动检测游戏）

```powershell
python .\scripts\game_client.py
```

常用参数示例：

```powershell
python .\scripts\game_client.py --walkthrough-game-name "<游戏名>"
python .\scripts\game_client.py --toggle-hotkey "ctrl+shift+g"
python .\scripts\game_client.py --walkthrough-base-url "http://127.0.0.1:9190"
```

### 3.2 单次检测游戏进程

```powershell
python .\scripts\game_detection.py
```

### 3.3 带重试检测（最多 5 次）

```powershell
python .\scripts\detect_game_with_retries.py
```

### 3.4 仅下载攻略

```powershell
python .\scripts\game_walkthrough_downloader.py "<游戏名>"
```

可选指定输出目录：

```powershell
python .\scripts\game_walkthrough_downloader.py "<游戏名>" .\walkthrough
```

### 3.5 导入攻略到服务

```powershell
python .\scripts\walkthrough_service_importer.py .\walkthrough\<游戏名>\text_images.json --instance-id "<游戏名>" --host "127.0.0.1:9190"
```

### 3.6 一键下载并导入

```powershell
python .\scripts\download_and_import_walkthrough.py "<游戏名>"
```

## 4. Skill 方式使用

项目内置了可被 AI智能体 调用的 Skill 定义：`SKILL.md`。

Skill 名称：`game-assistant-walkthrough`

该 Skill 支持两类意图：

1. 下载攻略（只下载并导入，不启动客户端）。
2. 打开攻略（可检测后启动，或带游戏名直启）。

### 4.1 典型触发语

- 我要玩游戏了
- 打开攻略
- 打开<游戏名>攻略
- 我要玩<游戏名>游戏了
- 下载攻略
- 下载<游戏名>攻略
- 更新攻略

### 4.2 执行行为（简述）

- 当用户语句明确带游戏名且是“打开攻略”意图时，优先直启：

```powershell
python .\scripts\game_client.py --walkthrough-game-name "<游戏名>"
```

- 当是“下载攻略”意图时，只执行下载导入：

```powershell
python .\scripts\download_and_import_walkthrough.py "<游戏名>"
```

- 若语句未明确游戏名，Skill 会先走检测流程：

```powershell
python .\scripts\detect_game_with_retries.py
```

并在拿到 `process` + `game_name` 后统一更新映射：

```powershell
python .\scripts\append_detected_process.py "<process>" "<game_name>"
```

## 5. 常见问题

### 5.1 运行 `game_client.py` 报缺少 Pillow/keyboard

安装依赖并重试：

```powershell
python -m pip install -r .\scripts\requirements.txt
```

### 5.2 检测不到游戏进程

- 确认游戏已进入 3D 渲染场景。
- 检查是否有权限差异（例如游戏管理员权限、Python 非管理员权限）。
- 可先执行：

```powershell
python .\scripts\detect_game_with_retries.py
```

查看返回 JSON 的 `status` / `process` 字段。

### 5.3 下载成功但导入失败

- 确认服务端 `127.0.0.1:9190` 可访问。
- 确认输出文件存在：`walkthrough/<游戏名>/text_images.json`。
