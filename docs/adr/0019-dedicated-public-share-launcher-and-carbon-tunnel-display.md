# Dedicated Public Share Launcher and Carbon Tunnel Display

We introduce an explicit, isolated launcher script (`run_aicovergen_share.bat`) and CLI forwarding (`launch.py --share`) to enable temporary Gradio public share links (`*.gradio.live`) on demand, capturing the tunnel URL and integrating it into the Carbon theme console display.

**Context & Problem:**
AICoverGen runs locally by default (`http://127.0.0.1:7860` and `http://0.0.0.0:7860`). Users occasionally need to access the WebUI from external devices (e.g. smartphones outside the local Wi-Fi, or sharing with trusted collaborators) without configuring router port-forwarding or dynamic DNS.
1. **Unintentional Exposure Risk:** Always enabling `--share` or prompting interactively on every launch exposes the local neural pipeline, file outputs (`song_output/`), and base workspace to the public internet unnecessarily.
2. **Missing Tunnel Visibility:** While `src/webui.py` supported Gradio's `--share` flag, `launch.py` did not accept or forward `--share`, and the custom log parser suppressed raw HTTP lines, hiding the ephemeral `*.gradio.live` link from the Carbon console interface.

**Considered Options:**
- *Always enable `--share` in `run_aicovergen.bat`* — Rejected: Security risk. Opens an unauthenticated public tunnel to the host machine on every execution, consumes Gradio tunnel quota, and slows down local startup.
- *Interactive prompt at startup (Ask user: 1. Local 2. Share)* — Rejected: Breaks one-click automated desktop launching and batch execution unattended workflows.
- *Dedicated launcher script (`run_aicovergen_share.bat`) with CLI forwarding and Carbon display* — Accepted:
  1. Preserves `run_aicovergen.bat` as 100% local/LAN only.
  2. Provides `run_aicovergen_share.bat` calling `launch.py --share` for deliberate, opt-in public sharing.
  3. `launch.py` forwards `--share` to `src/webui.py`, intercepts `https://*.gradio.live` via stream regex, awaits tunnel stabilization, and formats the URL in Carbon Cyan (`#1192e8`) inside the ready card.
  4. Ephemeral lifecycle: tunnel closes immediately when the terminal process terminates.

**Consequences:**
- Zero risk of accidental internet exposure during standard local sessions.
- Immediate 1-click access to public sharing when desired via `run_aicovergen_share.bat`.
- High visual harmony: Public URL is rendered cleanly inside the Carbon ready banner alongside Local and LAN addresses.
- Backward-compatible: Default launcher behavior remains completely unchanged.
