[English](./README_EN.md) | 简体中文

# 使用说明

> 此工具仅作演示用途，仅限个人使用，请勿商用。

欢迎使用[游戏助手标注工具](https://github.com/GameTechDev/IntelAIGamingAssistantLibrary/tree/main/demo/GameAssistantTool)。

`游戏助手标注工具`是用于游戏场景采集识别与攻略问答的桌面工具，支持 **GUI** 和 **CLI** 两种使用方式。

## 前提

使用前确保`游戏助手服务端`已经启动，服务地址默认为 `http://127.0.0.1:9190`。

如果是其它地址，请在GUI界面上点击“配置Host”或CLI传“--base-url”来指定当前服务地址。

工具的所有功能（场景采集、识别、问答）都依赖该服务，服务未启动时操作无效。

## 图形界面（GUI）的使用方式

解压GameAssistantTool.7z后 双击 `GameAssistantTool.exe` 即可打开 GUI 界面。


### 什么是目标

工具以**目标**来区分不同的游戏，所有场景数据和攻略文本都按目标单独存储。  

目标通常是游戏的**进程名**（即游戏 .exe 的文件名，不含后缀）。  

举例：游戏可执行文件是 `GameProcessName.exe`，则目标名为 `GameProcessName`。  


## 使用流程

### 场景识别

进入游戏 → 采集场景 → 构建场景库 → 添加提示内容 → 启动识别 → 识别到场景后弹出提示内容

### 攻略聊天框

添加攻略文本 → 构建攻略库 → 启动聊天框 → 询问攻略 → 返回攻略内容


## 使用方式详述

### 场景采集

**注意：采集场景时会旋转画面，如果采集过程中感到头晕不适，请勿盯着屏幕，将目光移出屏幕外稍作休息，<font color="red">若症状未缓解或加重，请及时就医。</font>**

#### 采集流程

1. 打开游戏，进入想要采集的场景（如某个关卡、某个 Boss 战画面）
2. 让游戏窗口处于**前台**（鼠标点一下游戏画面让它获得焦点）
3. 在 GUI 界面点击**采集**按钮，或直接按快捷键 `Alt + F12`
4. 在正式采集前，会提示把视角调整至水平位置，并且采集过程不要进行任何操作
5. 采集过程中工具会使用鼠标进行360°水平旋转场景来采集画面，转3圈采集上中下三个视角的360°画面。**如果采集过程中感到头晕不适，请勿盯着画面，将目光移出屏幕外稍作休息，<font color="red">若症状未缓解或加重，请及时就医。</font>**
6. 采集完成后会弹出提示，此时可以操作鼠标

**首次采集说明：** 由于每个游戏的鼠标灵敏度不同，第一次采集前会移动鼠标一段距离，并弹出输入框要求输入视角转动的角度，默认是90°。如果不确定，使用默认90°即可。


#### 编辑场景提示内容

采集完场景后，需要给每个场景填写对应的**提示内容**（即识别到该场景时弹出什么攻略文字）。

在 GUI 界面点击**编辑**按钮，找到刚才采集的场景，填入提示文字，保存即可。

举例：采集了某个 Boss 的场景，提示内容可以填写"该 Boss 弱点是火属性，建议使用火焰武器，注意躲避红色光柱"。


#### 构建场景库

采集并编辑好提示内容后，需要"构建"一次，工具才能在识别时使用这些数据。  

在 GUI 界面点击**构建**按钮（场景区域的构建），等待完成提示即可。  

每次新增、删除场景后，都需要重新构建一次。

仅修改提示内容时，不需要重新构建。因为提示内容由工具自己管理，不会提交到服务端。


### 场景识别

场景采集完成后，每次玩游戏时：

1. 打开游戏
2. 回到 GUI 界面，点击**启动**按钮，或按快捷键 `Alt + F9`
3. 界面提示识别中后，切回游戏正常游玩即可

工具会持续截取前台游戏画面，当画面与已采集的某个场景匹配时，**屏幕右上角会自动弹出该场景的提示内容**。

想暂停识别时，再按一次 `Alt + F9` 或点 GUI 的**停止**按钮。


### 攻略文本

攻略文本用于聊天问答功能，把游戏攻略的文字内容导入工具后，可以直接用自然语言提问。

**方式一：导入已有的 txt 文件**  
准备好攻略内容的 `.txt` 文件，在 GUI 界面攻略文本区域点击添加文件，选择该文件导入。

**方式二：直接新建**  
在 GUI 界面点击**新建**按钮，填写标题和内容后保存。

导入攻略文本后，同样需要构建一次才能在问答中使用。  

在 GUI 界面点击**构建**按钮（攻略文本区域的构建），等待完成提示即可。


### 攻略聊天框

在游戏过程中随时可以打开聊天框，向 AI 提问关于该游戏的问题。

按快捷键 `Alt + F10` 打开聊天框，直接输入问题发送，AI 会根据已导入的攻略文本作答。  

举例：输入"这个关卡的隐藏收集品在哪里"，AI 会在攻略文本中查找相关内容并回答。  

再按一次 `Alt + F10` 关闭聊天框。


## 快捷键

这三个快捷键是全局的，游戏全屏状态下同样有效，无需切出游戏。

如果快捷键与游戏有冲突，在 GUI 点击`快捷键设置`按钮自定义快捷键。

| 快捷键 | 功能 |
|--------|------|
| `Alt + F12` | 采集当前前台窗口的游戏场景 |
| `Alt + F10` | 打开 / 关闭攻略聊天框 |
| `Alt + F9` | 启动 / 停止场景识别 |


## 数据目录

工具的所有数据保存在程序目录下的 `saves` 文件夹中，按目标名分文件夹存放。

```
saves/
└── GameProcessName/          ← 目标名（游戏进程名）
    ├── scenes/               ← 场景采集的图片和数据
    └── knowledge/            ← 攻略文本（.txt 文件）
```

日志文件保存在 `logs/` 目录，按日期命名，出现问题时可以查看。


---


## CLI 使用（进阶）

不熟悉命令行的用户直接使用 GUI 即可，跳过本节。

CLI 工具为 `GameAssistantTool-cli.exe`，适合脚本化批处理场景。

格式（CLI）：

```bash
GameAssistantTool-cli.exe <subcommand> [options]
```

全局参数：

- `--base-url`（默认 `http://127.0.0.1:9190`）


### 采集场景

```bash
GameAssistantTool-cli.exe capture [--sensitivity-degree 90]
```

- 首次采集若未有标定数据，会进行灵敏度测量。
- 传 `--sensitivity-degree` 时，首次采集不再弹输入框确认。
- 返回 JSON 示例：

```json
{
  "game_process": "your_game_process",
  "scene_dir": "C:\\...\\saves\\your_game_process\\scenes\\001_20260605_120000",
  "scene_id": "your_game_process__001_20260605_120000",
  "image_count": 72
}
```

字段说明：

- `game_process`：本次采集目标（即 target）
- `scene_dir`：场景目录路径
- `scene_id`：场景 ID
- `image_count`：采集图片数量


### 场景列表与提示更新

查看已采集的场景列表：
```
GameAssistantTool-cli.exe scene-list [--target <target>]
```

更新指定场景的提示内容：
```
GameAssistantTool-cli.exe scene-prompt-update --target <target> --scene-id <scene_id> --prompt "新提示内容"
```

更新最近采集的场景的提示内容（采集后立刻补充提示时很方便）：
```
GameAssistantTool-cli.exe scene-prompt-update --target <target> --latest --prompt "新提示内容"
```


### 构建场景库

```bash
GameAssistantTool-cli.exe build-scenes --target <target> [--mode accurate|basic]
```

加 `accurate` 精度高速度慢，`basic` 速度快精度低，默认为 `accurate`。


### 单次识别

```
GameAssistantTool-cli.exe recognize-once --target <target> [--mode accurate|basic]
```

截取一次当前前台画面并识别，识别到场景时屏幕右上角弹出提示。


### 常驻识别

```
GameAssistantTool-cli.exe recognize-loop --target <target> [--mode accurate|basic] [--interval 1.0]
```

持续识别，效果与 GUI 场景识别一致。按 `Ctrl + C` 停止。

`--interval 1.0` 可调整识别间隔（单位：秒，默认 1 秒）。


### 攻略文本管理

导入 txt 文件：
```
GameAssistantTool-cli.exe guide-add --target <target> --file <path_to_txt>
```

直接新建一条攻略：
```
GameAssistantTool-cli.exe guide-new --target <target> --title <title> --content <content>
```


### 构建攻略库

```
GameAssistantTool-cli.exe build-guides --target <target>
```

### 攻略问答

```
GameAssistantTool-cli.exe ask --target <目标名> --text "问题内容"
```

举例：

```
GameAssistantTool-cli.exe ask --target GameProcessName --text "第三章隐藏 Boss 怎么触发"
```


### 删除目标数据

删除某个游戏的全部场景和攻略数据：
```
GameAssistantTool-cli.exe delete-instance --target <target>
```

> 此操作不可撤销，确认无需保留该游戏数据后再执行。


## 通过AI智能体（Agentic AI）调用工具

### 加载SKILL

在AI智能体里输入`加载skill /path/to/GameAssistantTool`，等待提示Skill加载成功即可。

### 不管是GUI模式还是CLI模式都需要让游戏窗口处于**前台**（鼠标点一下游戏画面让它获得焦点）之后才能正确采集！

### 开启GUI模式

在AI智能体里输入`启动游戏助手工具GUI模式`。等待工具 GUI 窗口出现即可！

### 开启CLI模式 （根据上述CLI命令以实际需求自由组合）

- 采集场景、编辑、构建场景，在AI智能体里输入`采集场景，场景完成后构建场景，添加提示内容“xxx”`。

- 识别场景，在AI智能体里输入`开启常驻识别`。

- 添加游戏攻略、构建攻略，在AI智能体里输入`添加攻略，攻略标题为XXX，攻略内容为XXX`。

- 攻略问答，在AI智能体里输入`xxx`。xxx 为提问的问题。