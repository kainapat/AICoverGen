# Carbon Theme Terminal Launcher and Deprecation Noise Suppression

We harmonize the terminal interface (`launch.py`) with the WebUI's IBM Carbon Design System, using high-readability Carbon Blue and Slate Gray accents, while completely suppressing noisy Python 3.10 and JavaScript runtime deprecation notices.

**Context & Problem:**
Previously, `launch.py` utilized a high-saturation "Cyberpunk / Neon Tech" color palette (hot Magenta `#d74bff`, Neon Cyan `#00f0ff`, and Dark Purple). While visually stylized, it suffered from several issues:
1. **Design Inconsistency:** The WebUI uses the IBM Carbon theme (`ibm-software/gradio-carbon-theme`), making the cyberpunk neon terminal feel disconnected from the actual application interface.
2. **Visual Fatigue:** Neon colors on dark terminal backgrounds reduced contrast and readability during extended sessions.
3. **Deprecation Noise:** Subprocess deprecation notices (such as Python 3.10 EOL warnings and missing JavaScript runtime alerts from yt-dlp) were displayed as persistent amber notifications, cluttering the pipeline progress.

**Considered Options:**
- Plain ASCII Terminal — rejected: Sacrifices live telemetry, box structuring, progress bars, and user-friendly step guidance.
- Keep Cyberpunk Theme with Minor Tweaks — rejected: Does not solve the aesthetic mismatch with the WebUI's Carbon theme.
- IBM Carbon Unified Terminal (`launch.py`) — accepted:
  1. Adopt the IBM Carbon palette:
     - Primary Accent: Carbon Blue 60 (`#4589ff` / `\033[38;2;69;137;255m`) and Carbon Blue 70 (`#0f62fe`).
     - Box Borders & Dividers: Slate Gray (`#525252` / `\033[38;2;82;82;82m`).
     - High-Contrast Text: Crisp White (`#f4f4f4`) and Light Silver (`#c6c6c6`).
     - Semantic Badges: Carbon Green 40 (`#42be65`) for success and Carbon Red 50 (`#fa4d56`) for errors.
  2. Redesign header banner as `AICoverGen v2.5 [CARBON CONSOLE]` with clean rounded borders.
  3. Filter out non-actionable library deprecation warnings (`Support for Python version... deprecated` and `No supported JavaScript runtime`).
  4. Retain crash-safety, WinError 10054 suppression, and atomic chunk counting.

**Consequences:**
- Visual continuity: Terminal launcher and WebUI share identical color tokens and visual language.
- Enhanced readability: Clean slate borders and carbon blue highlights provide superior contrast on both light and dark shell backgrounds.
- Zero clutter: Clean pipeline stream without irrelevant deprecation spam.
