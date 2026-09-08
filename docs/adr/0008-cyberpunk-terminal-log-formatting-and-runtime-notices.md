# Cyberpunk Terminal Log Formatting and Amber Runtime Notices

We transform raw subprocess output and library deprecation warnings into clean, categorized Cyberpunk Sub-steps and formatted Amber Runtime Notices in `launch.py`.

**Context & Problem:**
During audio pipeline execution, various backend libraries (yt-dlp, PyTorch, ONNX Runtime, librosa, noisereduce) print unformatted, raw informational logs directly to stdout/stderr.
Specifically:
1. **yt-dlp Deprecation Warning:** `Deprecated Feature: Support for Python version 3.10 has been deprecated. Please update to Python 3.11 or above`. This message caused confusion, leading users to believe their Python environment was outdated, even though Python 3.10 is strictly required on Windows for RVC's PyTorch + Fairseq C++ bindings.
2. **Raw Sub-step Clutter:** Messages such as `[*] Non-ASCII filename detected...`, `['CUDAExecutionProvider'] cuda:0`, `<All keys matched successfully>`, `Execution time: 14.5310 seconds`, `Audio duration: 254.56 seconds`, and `Noice reduce` appeared as raw gray text between primary pipeline stages, degrading readability and visual hierarchy.

**Considered Options:**
- Suppress all secondary stdout lines entirely — rejected: Users lose useful feedback on model weight matching, inference speed, and audio routing.
- Leave lines unformatted in raw text — rejected: Clutters the terminal interface and causes alarm over harmless deprecation notices.
- Cyberpunk Sub-step Parser & Amber Runtime Notice in `launch.py` — accepted: Intercepts raw stream lines in `format_log_line`:
  - Translates the Python 3.10 deprecation notice into a bold, reassuring Amber notice: `⚠️  [RUNTIME NOTICE] Python 3.10 active (standard engine for PyTorch + Fairseq)`.
  - Parses raw sub-steps into neatly indented (`     `), icon-embellished entries:
    - `🛡️  [ASCII-Safe Routing]` for Unicode filename protection.
    - `🎮  [ONNX Engine]` & `💾  [VRAM Allocation]` for GPU inference telemetry.
    - `✔   [RVC Weights]` for model loading confirmation.
    - `⚡  [RVC Speed]` combining execution time and audio duration into an intuitive real-time multiplier (e.g. `17.5x Real-time`).
    - `✨  [Audio Mastering]` for noise reduction.

**Consequences:**
- The terminal presents a cohesive, readable, professional visual hierarchy.
- Deprecation warnings are explained in context rather than alarming the user.
- Inference performance is immediately clear through real-time ratio metrics.
