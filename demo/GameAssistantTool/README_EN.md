English | [简体中文](./README.md)

# User Guide

Welcome to the [GameAssistantTool](https://github.com/GameTechDev/IntelAIGamingAssistantLibrary/tree/main/demo/GameAssistantTool).

GameAssistantTool is a desktop tool for game scene capture/recognition and strategy Q&A. It supports both **GUI** and **CLI** usage.

## Prerequisites

Before using the tool, make sure the `GameAssistantToolServer` is already running. The default service URL is `http://127.0.0.1:9190`.

If you use another address, click "Configure Host" in the GUI or pass `--base-url` in CLI to specify the current service URL.

All tool features (scene capture, recognition, and Q&A) depend on this service. If the service is not running, operations will not work.

## GUI Usage

After extracting GameAssistantTool.7z, double-click `GameAssistantTool.exe` to open the GUI.

### What Is a Target

The tool uses a **target** to distinguish different games. All scene data and strategy text are stored separately by target.

A target is usually the game **process name** (the game `.exe` filename without extension).

Example: if the executable is `GameProcessName.exe`, then the target name is `GameProcessName`.

## Workflow

### Scene Recognition

Enter game -> Capture scene -> Build scene library -> Add prompt content -> Start recognition -> Prompt content pops up after recognition

### Strategy Chatbox

Add strategy text -> Build strategy library -> Start chatbox -> Ask strategy question -> Get strategy response

## Detailed Usage

### Scene Capture

**Note: Scene capture rotates the camera view. If you feel dizzy or uncomfortable during capture, do not stare at the screen. Look away and rest briefly. <font color="red">If symptoms do not improve or become worse, seek medical help promptly.</font>**

#### Capture Steps

1. Open the game and enter the scene you want to capture (for example, a level or a Boss fight screen).
2. Make sure the game window is in the **foreground** (click the game screen once to give it focus).
3. In the GUI, click the **Capture** button, or press hotkey `Alt + F12`.
4. Before formal capture, the tool will prompt you to adjust the camera to a horizontal position. Do not perform any operation during capture.
5. During capture, the tool uses the mouse to rotate horizontally by 360° to capture images. It rotates 3 circles to capture upper/middle/lower viewpoints. **If you feel dizzy or uncomfortable during capture, do not stare at the screen. Look away and rest briefly. <font color="red">If symptoms do not improve or become worse, seek medical help promptly.</font>**
6. After capture is finished, a prompt will appear, and you can operate the mouse again.

**First-time capture note:** Since mouse sensitivity differs by game, before the first capture the tool will move the mouse by a certain distance and show an input box asking for camera rotation angle. The default is 90°. If unsure, use the default 90°.

#### Edit Scene Prompt Content

After capturing scenes, you need to fill in the corresponding **prompt content** for each scene (what strategy text should pop up when this scene is recognized).

In the GUI, click the **Edit** button, find the scene you just captured, enter prompt text, and save.

Example: for a captured Boss scene, prompt content can be "This Boss is weak to fire. Use fire weapons and watch out for red light beams.".

#### Build Scene Library

After scene capture and prompt editing, you need to run one "build" so the tool can use these data for recognition.

In the GUI, click the **Build** button (build in the scene section) and wait for completion prompt.

You must rebuild every time you add or delete scenes.

If you only modify prompt content, rebuilding is not required. Prompt content is managed by the tool itself and is not submitted to the server.

### Scene Recognition

After scene capture is completed, each time you play:

1. Open the game.
2. Return to GUI, click the **Start** button, or press hotkey `Alt + F9`.
3. After the GUI indicates recognition is running, switch back to the game and play normally.

The tool continuously captures the foreground game screen. When the image matches a captured scene, **the corresponding prompt content will automatically pop up at the top-right corner of the screen**.

To pause recognition, press `Alt + F9` again or click the GUI **Stop** button.

### Strategy Text

Strategy text is used by the chat Q&A feature. After importing strategy text into the tool, you can ask questions in natural language.

**Method 1: Import an existing txt file**
Prepare a `.txt` file with strategy content. In the strategy text section of GUI, click add file and import it.

**Method 2: Create directly**
In GUI, click the **New** button, fill in title and content, then save.

After importing strategy text, you also need to build once before it can be used for Q&A.

In GUI, click the **Build** button (build in the strategy text section) and wait for completion prompt.

### Strategy Chatbox

You can open the chatbox anytime during gameplay and ask AI questions about the game.

Press hotkey `Alt + F10` to open the chatbox, type your question, and send. The AI answers based on imported strategy text.

Example: input "Where are the hidden collectibles in this level?". The AI will look up relevant content in strategy text and answer.

Press `Alt + F10` again to close the chatbox.

## Hotkeys

These three hotkeys are global and still work in fullscreen game mode without switching out of the game.

If hotkeys conflict with the game, click the `Hotkey Settings` button in GUI to customize hotkeys.

| Hotkey | Function |
|--------|----------|
| `Alt + F12` | Capture game scene of current foreground window |
| `Alt + F10` | Open / close strategy chatbox |
| `Alt + F9` | Start / stop scene recognition |

## Data Directory

All tool data are saved in the `saves` folder under the program directory, with one folder per target name.

```text
saves/
└── GameProcessName/          <- Target name (game process name)
    ├── scenes/               <- Captured scene images and data
    └── knowledge/            <- Strategy text (.txt files)
```

Log files are saved in the `logs/` directory and named by date. Check them when issues occur.

---

## CLI Usage (Advanced)

If you are not familiar with command line usage, just use GUI and skip this section.

The CLI tool is `GameAssistantTool-cli.exe`, suitable for scripted batch scenarios.

Format (CLI):

```bash
GameAssistantTool-cli.exe <subcommand> [options]
```

Global option:

- `--base-url` (default `http://127.0.0.1:9190`)

### Capture Scene

```bash
GameAssistantTool-cli.exe capture [--sensitivity-degree 90]
```

- If there is no calibration data for first-time capture, sensitivity measurement will be performed.
- If `--sensitivity-degree` is provided, the first capture will not show the confirmation input box.
- Sample returned JSON:

```json
{
  "game_process": "your_game_process",
  "scene_dir": "C:\\...\\saves\\your_game_process\\scenes\\001_20260605_120000",
  "scene_id": "your_game_process__001_20260605_120000",
  "image_count": 72
}
```

Field descriptions:

- `game_process`: target of this capture (i.e., target)
- `scene_dir`: scene directory path
- `scene_id`: scene ID
- `image_count`: number of captured images

### Scene List and Prompt Update

View captured scene list:

```bash
GameAssistantTool-cli.exe scene-list [--target <target>]
```

Update prompt content for a specified scene:

```bash
GameAssistantTool-cli.exe scene-prompt-update --target <target> --scene-id <scene_id> --prompt "new prompt content"
```

Update prompt content for the most recently captured scene (convenient for adding prompt immediately after capture):

```bash
GameAssistantTool-cli.exe scene-prompt-update --target <target> --latest --prompt "new prompt content"
```

### Build Scene Library

```bash
GameAssistantTool-cli.exe build-scenes --target <target> [--mode accurate|basic]
```

`accurate` provides higher accuracy but slower speed. `basic` is faster but lower accuracy. Default is `accurate`.

### Single Recognition

```bash
GameAssistantTool-cli.exe recognize-once --target <target> [--mode accurate|basic]
```

Capture the current foreground screen once and recognize it. If a scene is recognized, prompt content pops up at the top-right corner.

### Continuous Recognition

```bash
GameAssistantTool-cli.exe recognize-loop --target <target> [--mode accurate|basic] [--interval 1.0]
```

Runs continuous recognition, consistent with GUI scene recognition behavior. Press `Ctrl + C` to stop.

`--interval 1.0` adjusts recognition interval (in seconds, default 1 second).

### Strategy Text Management

Import a txt file:

```bash
GameAssistantTool-cli.exe guide-add --target <target> --file <path_to_txt>
```

Create a strategy item directly:

```bash
GameAssistantTool-cli.exe guide-new --target <target> --title <title> --content <content>
```

### Build Strategy Library

```bash
GameAssistantTool-cli.exe build-guides --target <target>
```

### Strategy Q&A

```bash
GameAssistantTool-cli.exe ask --target <target_name> --text "question text"
```

Example:

```bash
GameAssistantTool-cli.exe ask --target GameProcessName --text "How do I trigger the hidden Boss in Chapter 3?"
```

### Delete Target Data

Delete all scene and strategy data for a game:

```bash
GameAssistantTool-cli.exe delete-instance --target <target>
```

> This operation is irreversible. Make sure you do not need to keep this game data before running it.

## Call the Tool via Agentic AI

### Load SKILL

In the AI agent, input `load skill /path/to/GameAssistantTool` and wait for the prompt indicating SKILL was loaded successfully.

### For both GUI mode and CLI mode, you must keep the game window in the **foreground** (click the game screen once to give it focus) before capture can work correctly.

### Start GUI Mode

In the AI agent, input `start game assistant tool GUI mode`. Wait for the tool GUI window to appear.

### Start CLI Mode (combine the CLI commands above according to your actual needs)

- For scene capture, editing, and scene build, input `capture scene, build scenes after capture, add prompt content "xxx"` in the AI agent.
- For scene recognition, input `start continuous recognition` in the AI agent.
- For adding game strategy and building strategy library, input `add strategy, strategy title is XXX, strategy content is XXX` in the AI agent.
- For strategy Q&A, input `xxx` in the AI agent, where xxx is your question.
