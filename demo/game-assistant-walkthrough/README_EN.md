English | [简体中文](./README.md)

# Game Assistant Walkthrough Guide

Welcome to the [Game Assistant Walkthrough Tool](https://github.com/GameTechDev/IntelAIGamingAssistantLibrary/tree/main/demo/game-assistant-walkthrough).

A game walkthrough assistant tool with two supported usage modes:

1. Run directly with Python scripts (local CLI mode).
2. Invoke the Skill through an Agent (natural language mode).

Core capabilities:

- Detect the current game process (based on GPU Engine usage).
- Automatically download and organize text-image walkthrough content (current implementation parses Gamersky pages).
- Import walkthrough content into the game assistant service (Knowledge/Vision).
- Launch a desktop walkthrough overlay client, with optional direct start by game name.

## Important Language Notes

- The walkthrough download source, Gamersky (游民星空), is a Chinese game guide website.
- Walkthrough content downloaded from this source is Chinese.
- If you need English walkthrough downloads, you must implement your own downloader/integration code for an English source.
- `game_client.py` UI/text is currently in Chinese.

## 0. Prerequisites

Before using this tool, make sure the `game assistant backend service` is already running, as scene recognition depends on it.

By default, the tool connects to the game assistant service at: `127.0.0.1:9190`.

If your service is not running at the default address, specify it via command-line arguments.

## 1. Project Structure

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

The following files/directories are generated at runtime:

- `walkthrough/`: downloaded walkthrough data and intermediate files.
- `logs/`: runtime logs for `game_client.py`.
- `detected_processes.json`: process-to-game-name mapping (maintained by `append_detected_process.py`).

## 2. Requirements

- OS: Windows (current process detection depends on Win32/PDH APIs).
- Python: recommended 3.10+.

Install dependencies:

```powershell
python -m pip install -r .\scripts\requirements.txt
```

`tkinter` is usually bundled with Python on Windows. If you use a minimal Python distribution, verify that tkinter is available.

## 3. Python Usage

Run the following commands from the project root.

### 3.1 Start the Walkthrough Client (auto game detection)

```powershell
python .\scripts\game_client.py
```

Common argument examples:

```powershell
python .\scripts\game_client.py --walkthrough-game-name "<game_name>"
python .\scripts\game_client.py --toggle-hotkey "ctrl+shift+g"
python .\scripts\game_client.py --walkthrough-base-url "http://127.0.0.1:9190"
```

### 3.2 Single-shot Game Process Detection

```powershell
python .\scripts\game_detection.py
```

### 3.3 Detection with Retries (up to 5 attempts)

```powershell
python .\scripts\detect_game_with_retries.py
```

### 3.4 Download Walkthrough Only

```powershell
python .\scripts\game_walkthrough_downloader.py "<game_name>"
```

Optional output directory:

```powershell
python .\scripts\game_walkthrough_downloader.py "<game_name>" .\walkthrough
```

### 3.5 Import Walkthrough to Service

```powershell
python .\scripts\walkthrough_service_importer.py .\walkthrough\<game_name>\text_images.json --instance-id "<game_name>" --host "127.0.0.1:9190"
```

### 3.6 Download and Import in One Step

```powershell
python .\scripts\download_and_import_walkthrough.py "<game_name>"
```

## 4. Agent Skill Usage

This project includes a Skill definition that can be invoked by an Agent: `SKILL.md`.

Skill name: `game-assistant-walkthrough`

The Skill supports two intents:

1. Download walkthrough (download + import only, without launching the client).
2. Open walkthrough (launch after detection, or direct launch with explicit game name).

### 4.1 Typical Trigger Phrases

- I am going to play a game
- Open walkthrough
- Open walkthrough for <game_name>
- I am going to play <game_name>
- Download walkthrough
- Download walkthrough for <game_name>
- Update walkthrough

### 4.2 Agent Execution Behavior (Summary)

- If the user intent is "open walkthrough" and the game name is explicit, direct launch is preferred:

```powershell
python .\scripts\game_client.py --walkthrough-game-name "<game_name>"
```

- If the intent is "download walkthrough", run download + import only:

```powershell
python .\scripts\download_and_import_walkthrough.py "<game_name>"
```

- If game name is not explicit, the Skill starts with detection:

```powershell
python .\scripts\detect_game_with_retries.py
```

Then, after obtaining both `process` and `game_name`, it updates the mapping:

```powershell
python .\scripts\append_detected_process.py "<process>" "<game_name>"
```

## 5. Troubleshooting

### 5.1 `game_client.py` reports missing Pillow/keyboard

Install dependencies and retry:

```powershell
python -m pip install -r .\scripts\requirements.txt
```

### 5.2 Game process is not detected

- Ensure the game has entered a 3D rendering scene.
- Check privilege mismatch (for example, game runs as admin while Python does not).
- Run:

```powershell
python .\scripts\detect_game_with_retries.py
```

Then inspect `status` and `process` in the returned JSON.

### 5.3 Download succeeded but import failed

- Ensure service endpoint `127.0.0.1:9190` is reachable.
- Ensure output file exists: `walkthrough/<game_name>/text_images.json`.
