---
name: "game-assistant"
description: "游戏辅助工具，用于场景采集、场景识别与攻略问答；适合 OpenClaw/Hermes 等 agent 直接通过 skill 或 CLI 调用。快捷键: Alt+F12采集, Alt+F9识别, Alt+F10聊天。Invoke when user needs to capture game scenes, recognize scenes, or query/update game guides."
---

# Game Assistant Tool

> **⚠️ 重要快捷键提示（GUI）**
> - `Alt + F12` - 采集场景
> - `Alt + F9` - 启动/停止场景识别
> - `Alt + F10` - 打开/关闭攻略聊天框

游戏场景采集识别与攻略问答工具，支持 GUI 和 CLI 两种使用方式。  
**给 agent 的建议**：如果你的任务是“采集场景 / 识别场景 / 更新场景提示”，优先走 CLI，便于脚本化与批处理。

## 1. 使用方式

### 1. 启动 GUI 界面

直接运行：

```bash
GameAssistantTool.exe
```

GUI 可用于：
- 场景采集、编辑、构建
- 场景识别（启动/停止）
- 攻略文本管理
- 攻略聊天框

### 2. CLI 命令（推荐给 agent）

#### 场景采集
```bash
GameAssistantTool-cli.exe capture [--sensitivity-degree 90]
```

- 返回 JSON，`game_process` 就是 target。
- 示例返回：
```json
{
  "game_process": "your_game_process",
  "scene_dir": "C:\\...\\saves\\your_game_process\\scenes\\001_20260605_120000",
  "scene_id": "your_game_process__001_20260605_120000",
  "image_count": 72
}
```

#### 构建场景
```bash
GameAssistantTool-cli.exe build-scenes --target <target> [--mode accurate|basic]
```

#### 构建攻略
```bash
GameAssistantTool-cli.exe build-guides --target <target>
```

#### 单次识别
```bash
GameAssistantTool-cli.exe recognize-once --target <target> [--mode accurate|basic] [--topk 5]
```

#### 常驻识别
```bash
GameAssistantTool-cli.exe recognize-loop --target <target> [--mode accurate|basic] [--topk 5] [--interval 1.0]
```

- 持续识别前台窗口，命中场景后输出提示内容。

#### 攻略问答
```bash
GameAssistantTool-cli.exe ask --target <target> --text "问题"
```

#### 攻略文本管理
```bash
GameAssistantTool-cli.exe guide-add --target <target> --file <path_to_txt>
GameAssistantTool-cli.exe guide-new --target <target> --title <title> --content <content>
```

#### 删除目标数据
```bash
GameAssistantTool-cli.exe delete-instance --target <target>
```

#### 场景列表与提示更新
```bash
GameAssistantTool-cli.exe scene-list [--target <target>]
GameAssistantTool-cli.exe scene-prompt-update --target <target> --scene-id <scene_id> --prompt "新提示内容"
GameAssistantTool-cli.exe scene-prompt-update --target <target> --latest --prompt "新提示内容"
```

## 3. 全局参数

- `--base-url`：API地址（默认 `http://127.0.0.1:9190`）

## 4. 热键（GUI模式）

- `Alt + F12`：采集场景
- `Alt + F9`：启动/停止场景识别
- `Alt + F10`：打开/关闭攻略聊天框

## 5. 数据目录

本地数据存储在 `./saves` 目录：
- `saves/<target>/scenes/`：场景采集数据
- `saves/<target>/knowledge/*.txt`：攻略文本