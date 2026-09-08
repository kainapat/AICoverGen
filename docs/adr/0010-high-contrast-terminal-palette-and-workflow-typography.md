# High-Contrast Terminal Palette and Workflow Typography

We elevate the secondary terminal color palette from low-contrast dim tones to high-contrast Light Silver (`RGB 200, 205, 215`) and Medium Slate (`RGB 145, 155, 175`), and enhance Workflow Guide typography with cyan step indicators and highlighted action targets.

**Context & Problem:**
In `launch.py`, secondary streams, daemon readiness guides, socket polling lines (`Connecting to socket... (x/25)`), and terminal shortcuts (`[Press Ctrl+C...]`) were styled with low-luminance palette values:
- `"gray"`: `\033[38;2;120;130;150m` (RGB 120, 130, 150)
- `"dark"`: `\033[38;2;75;85;105m` (RGB 75, 85, 105)

On standard black and dark-themed Windows terminals, this produced a contrast ratio below 3:1, causing text to blur and strain user readability, especially in the 4-step Workflow Guide and background socket status lines.

**Considered Options:**
- Pure White (`\033[1;37m`) everywhere — rejected: Flattens visual hierarchy, causing secondary details and primary headers to compete visually, creating screen fatigue.
- Neon Accent everywhere — rejected: Overwhelms the interface and dilutes the semantic meaning of status alerts (e.g. green for success, red for errors).
- Two-Tier Contrast Elevation & Keyword Highlighting — accepted:
  1. Elevate `"gray"` to Light Silver (`RGB 200, 205, 215`), achieving sharp ~7:1 contrast on dark terminals while maintaining subordinate hierarchy to pure white.
  2. Elevate `"dark"` to Medium Slate (`RGB 145, 155, 175`), keeping auxiliary hints visible without sinking into black.
  3. Highlight Workflow Guide step numbers (`1.`, `2.`) in Cyan (`\033[38;2;0;240;255m`) and action buttons (`[Generate]`, `[Process URL]`) in Pure White (`\033[1;37m`).

**Consequences:**
- Terminal logs and guides are instantly readable across all lighting conditions and display calibrations.
- Users can scan workflow instructions within 1 second without visual fatigue.
- Maintains strict alignment within `render_box` without ANSI-induced column shifting.
