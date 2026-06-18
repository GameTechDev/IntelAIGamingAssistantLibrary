---
name: game-assistant-walkthrough
description: "启动游戏攻略助手与下载攻略流程。用于用户说‘我要玩游戏了’、‘我要玩XXX游戏了’、‘打开攻略’、‘打开XXX攻略’、‘开始游戏’、‘启动攻略助手’、‘下载攻略’、‘下载XXX攻略’、‘更新攻略’等场景：先判断用户意图；若是下载攻略，仅下载并导入，不启动 game_client.py；若是打开攻略且原话明确带游戏名（如‘打开XXX攻略’、‘我要玩XXX游戏了’），直接启动 game_client.py 并传 --walkthrough-game-name；否则按原流程检测游戏后再启动。"
argument-hint: "可选：用户原话（例如：我要玩游戏了）"
user-invocable: true
---

# Game Assistant Walkthrough

## 使用时机
- 用户表达要开始玩游戏并打开攻略助手，或明确要求下载/更新攻略。
- 常见触发语：
1. 我要玩游戏了
2. 打开攻略
3. 开始游戏
4. 启动攻略助手
5. 下载攻略
6. 下载XXX攻略
7. 更新攻略
8. 打开XXX攻略
9. 我要玩XXX游戏了

## 目标
1. 先识别用户意图：`下载攻略` 或 `打开攻略`。
2. 两种意图都可复用同一套游戏名获取机制（原话提取、游戏检测、联网补全映射）。
3. 当意图为 `下载攻略` 时，只执行下载与导入，不启动 `game_client.py`。
4. 当意图为 `打开攻略` 且原话明确给出游戏名时，直接启动 `game_client.py --walkthrough-game-name <game_name>`。
5. 当意图为 `打开攻略` 且原话未明确给出游戏名时，按原流程检测后启动 `game_client.py`。
6. 只要最终得到 `process` 和 `game_name`，都必须写入（或更新）`detected_processes.json`，不能仅在“联网补全”分支写入。

## 意图分流规则
1. 若用户原话包含 `下载攻略`、`下载XXX攻略`、`更新攻略` 等下载/更新诉求，判定为 `下载攻略`。
2. 若用户原话包含 `打开攻略`、`我要玩游戏了`、`开始游戏`、`启动攻略助手` 等开启助手诉求，判定为 `打开攻略`。
3. 当同一句里同时出现下载与打开含义时，优先按用户的下载诉求执行，即先判定为 `下载攻略`。
4. 若用户原话属于 `打开XXX攻略`、`我要玩XXX游戏了` 这类“打开攻略 + 明确游戏名”表达，进入“打开攻略-直启分支”。

## 识别用户原话中的游戏名
1. 优先读取 skill 参数里的用户原话。
2. 如果原话清楚表达了目标游戏名，则直接使用，不运行检测。
3. 可接受的明确表达包括但不限于：
1. `下载黑神话悟空攻略`
2. `帮我下载黑神话悟空的攻略`
3. `更新一下黑神话悟空攻略`
4. 仅移除动作词和尾部的 `攻略`、`的攻略`、`图文攻略` 等固定修饰，不要擅自改写游戏名。
5. 如果原话里没有明确游戏名，或游戏名提取后仍明显为空，再进入“游戏检测”步骤。

## 打开攻略-直启分支（新增）
触发条件：
1. 意图已判定为 `打开攻略`。
2. 用户原话可稳定提取出明确 `game_name`，典型如：`打开XXX攻略`、`我要玩XXX游戏了`。

执行规则：
1. 命中该分支时，不运行 `detect_game_with_retries.py`。
2. 直接启动客户端并传参：
```powershell
python ./scripts/game_client.py --walkthrough-game-name XXX
```
3. 其中 `XXX` 必须替换为从用户原话提取到的 `game_name`。
4. 若提取失败或结果为空，则回退到“游戏检测”流程。

## 游戏检测
在当前 skill 目录执行检测命令（该脚本内部会执行 `game_detection.py`，并按 1 秒间隔最多重试 5 次）：
```powershell
python ./scripts/detect_game_with_retries.py
```
解析标准输出 JSON，重点读取 `process`、`name`。

分支规则：
1. `process为null`：表示 `process` 在 5 次内始终为空，直接结束 skill，不启动 `game_client.py`。
2. `process不为null 并且 name为null或空`：表示 `process` 非空但 `name` 为空，进入“联网补全游戏名”。
3. `name不为null且不为空`：表示 `name` 已存在，直接作为后续动作所需的游戏名。

## 联网补全游戏名（必须由 agent 完成）
1. 使用 agent 的联网能力（如网页检索/浏览）搜索：`<process> 对应的游戏名`。
2. 禁止写脚本调用搜索引擎 API。
3. 选择最可信的中文游戏名（优先官方名称或高可信来源交叉验证）。
4. 若无法可靠确定游戏名，结束 skill，不要猜测写入。
5. 联网补全得到 `game_name` 后，进入下方“写入 detected_processes.json（统一规则）”步骤。

## 写入 detected_processes.json（统一规则）
适用时机：只要当前已经拿到 `process`（非空）和最终 `game_name`（非空），无论 `game_name` 来源于“原话提取”“检测结果 name”“联网补全”，都执行以下写入。

1. 不再在 skill 内手动读写 JSON，统一调用脚本：
```powershell
python ./scripts/append_detected_process.py "<process>" "<game_name>"
```
2. 由该脚本负责以下行为：
	- 目标文件为当前 skill 目录上层目录的 `detected_processes.json`。
	- 若文件不存在则创建，并以空对象 `{}` 初始化。
	- 以 JSON 对象映射写入：`{"process_name": "game_name"}`。
	- 若 key 已存在则更新为最新 `game_name`。
	- 若原文件内容为空或 JSON 非法，按空对象 `{}` 处理后再写入。
3. 该步骤在两种意图下都必须执行：只要 `process` 和最终 `game_name` 都非空，就先调用写入脚本，再进入后续动作。

## 动作执行

首先需要确保python环境的已安装这些依赖库：tkinter、pillow、keyboard、pyaudio、pyperclip、pystray、beautifulsoup4。

当你已经得到最终 `game_name` 后，按意图执行：

1. 当意图为 `下载攻略`：只下载并导入，不启动客户端。
```powershell
python ./scripts/download_and_import_walkthrough.py "<game_name>"
```

2. 当意图为 `打开攻略` 且命中“打开攻略-直启分支”：直接按带参命令启动客户端。
```powershell
python ./scripts/game_client.py --walkthrough-game-name "<game_name>"
```

3. 当意图为 `打开攻略` 且未命中“打开攻略-直启分支”：按原流程启动客户端。
```powershell
python ./scripts/game_client.py
```

补充约定：
1. 下载目录固定为当前目录下的 `walkthrough/`。
2. 导入时 `instance_id` 使用最终的 `game_name`。
3. `json_path` 使用 `walkthrough/<safe_game_name>/text_images.json`。

## 完成条件
- 当意图为 `下载攻略`：已完成攻略下载并成功导入；或
- 当意图为 `打开攻略`：成功启动 `game_client.py`；或
- `process` 连续 5 次检测为空并按规则结束。