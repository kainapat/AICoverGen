---
title: AICoverGen
emoji: 🚀
colorFrom: red
colorTo: pink
sdk: gradio
sdk_version: 5.44.0
app_file: app.py
pinned: false
license: mit
---

# AICoverGen  

## Overview  
**AICoverGen** is a WebUI designed to create **AI-powered song covers** with customizable voice models, pitch adjustments, and audio mixing options.  
Built with ❤️ for music enthusiasts and creators, it allows you to transform vocals, generate new covers, and manage models easily.  

| Description | Link |  
| ----------- | ---- |  
| 📙 Colab Notebook | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/R3gm/AICoverGen/blob/main/colab_notebook.ipynb) |  
| 🎉 Repository | [![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-black?style=flat-square&logo=github)](https://github.com/R3gm/AICoverGen) |  
| 🚀 Online DEMO | [![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-blue)](https://huggingface.co/spaces/r3gm/AICoverGen) |  

## Key Functions  
1. **Voice Models**  
   - Store models inside the folder: `AICoverGen/rvc_models`.  
   - Use the **Refresh Models 🔁** button after adding new ones.  

2. **Audio Input**  
   - Upload audio files (songs, recordings).  
   - Paste a **YouTube URL** for direct processing.  

3. **Pitch Control**  
   - **Pitch Change (Vocals ONLY):** Adjust pitch for male ↔ female conversions (`+1` / `-1`).  
   - **Overall Pitch Change:** Shift pitch/key of both vocals & instrumentals (semitones).  

4. **Voice Conversion Options**  
   - Apply trained voice models to replace original vocals with AI-generated ones.  

5. **Audio Mixing Options**  
   - Balance vocals and background for best quality results.  

6. **Cover Generation**  
   - Generate AI covers and download the final track.  

## Local Windows Setup (RTX 2050 4GB)

### Quick Start

| Method | Command |
|---|---|
| Double-click (recommended) | `run_aicovergen.bat` |
| PowerShell | `python launch.py` |
| Simple (classic CMD) | `start_simple.bat` |
| Manual | `.\.venv\Scripts\python.exe src\webui.py --listen --listen-port 7860` |

Open `http://127.0.0.1:7860` in your browser.

### Terminal Output

The launcher shows live progress with per-stage timing:

```
[18:15:02] [~] Starting AI Cover Generation Pipeline...
[18:15:05] [~] Downloading song... [+3s]
[18:15:20] [~] Separating Vocals from Instrumental... [+15s]
[18:17:45] [~] Separating Main Vocals from Backup Vocals... [+2m 25s]
[18:19:30] [~] Converting voice using RVC... [+1m 20s]
[+] Total time all process: 7m 8s (428.1s)
```

Each `[+Xs]` / `[+Xm XXs]` shows time spent since the previous stage.
`[+] Total time all process` shows the full pipeline duration.

### RTX 2050 4GB Optimization

No code changes needed — the codebase auto-detects VRAM:

- Half precision (FP16) on CUDA — halves VRAM usage
- MDX uses 1 thread when VRAM < 8GB (`mdx.py`)
- RVC uses reduced padding when VRAM <= 4GB (`rvc.py`: `x_pad=1, x_query=5, x_center=30, x_max=32`)

### YouTube Support

Standard, Mobile, Short, Embed, Playlist, and **YouTube Music** (`music.youtube.com`) links all work.

### Built-in Audio Player

Add `--builtin-player` to play the result directly in the WebUI instead of only downloading:

```
.\.venv\Scripts\python.exe src\webui.py --listen --listen-port 7860 --builtin-player
```

## Summary Table  

| Function                  | Description                                                                 |
|---------------------------|-----------------------------------------------------------------------------|
| **Voice Models**          | Manage voice models in the `rvc_models` folder.                             |
| **Audio Upload**          | Import audio via file upload or YouTube URL.                                |
| **Pitch Change (Vocals)** | Adjust pitch for gender conversion of vocals only.                          |
| **Overall Pitch Change**  | Modify the pitch/key of both vocals and instrumentals together.              |
| **Voice Conversion**      | Replace original vocals with selected AI voice models.                      |
| **Audio Mixing**          | Fine-tune balance between vocals and instrumentals.                         |
| **Generate & Download**   | Create your AI cover and download the result as an audio file.               |

👉 This is just a fork of [SociallyIneptWeeb/AICoverGen](https://github.com/SociallyIneptWeeb/AICoverGen), playing around with some changes and improvements.
