# Smart Launcher Batch File

We use `run_aicovergen.bat` as the primary way to start the WebUI locally. It kills orphaned processes on port 7860, checks Python availability, launches with logging, and verifies startup within 15 seconds. This was chosen over a simple `python src/webui.py --listen` because recurring orphaned processes and port conflicts made manual startup unreliable on Windows.

**Considered Options:**
- Simple batch file (just run python) — rejected: doesn't handle port conflicts
- No batch file (manual CLI) — rejected: users had recurring issues with orphaned processes
- Smart batch file with cleanup + logging — accepted

**Consequences:** The batch file hardcodes `D:\Code\AICoverGen` paths. Moving the project requires updating the batch file. The `cd /d "%~dp0"` line ensures it works from any working directory.
