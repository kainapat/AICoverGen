# Reliable Launcher Shutdown Design

## Goal

Make both Windows launchers cancel the active AICoverGen operation and terminate every owned process when the user presses `Ctrl+C` or closes the terminal window with the `X` button.

## Scope

The change applies to:

- `run_aicovergen.bat`
- `run_aicovergen_share.bat`
- `launch.py`
- The WebUI process and descendants it creates, including FFmpeg, SoX, Python workers, and the Gradio `frpc` public tunnel

The audio pipeline, WebUI behavior, model loading, and output formats are unchanged.

## Shutdown Contract

- `Ctrl+C` requests an orderly shutdown, waits no more than three seconds, then forcibly terminates the remaining process tree.
- Closing the terminal window with `X` cancels immediately. It must not depend on Python `finally` blocks because Windows can terminate the launcher before cleanup code completes.
- Shutdown must work during startup checks, WebUI initialization, public-tunnel setup, active generation, and the steady-state server wait.
- Port 7860 must be released after shutdown so either launcher can start again immediately.
- Public mode must also terminate the Gradio `frpc` tunnel.

## Architecture

### Process Group

The launcher starts `src/webui.py` in a new Windows process group while retaining the same console. This prevents the child from independently consuming the user's `Ctrl+C` and allows the parent launcher to send a targeted `CTRL_BREAK_EVENT` for orderly shutdown.

### Kill-on-Close Job Object

Immediately after spawning the WebUI, the launcher assigns it to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Descendants inherit the job. If Windows closes the launcher abruptly, the launcher-owned Job handle closes and the operating system terminates every process in the job without relying on application cleanup code.

Failure to establish the Job Object is a startup failure because continuing would violate the close-button shutdown contract.

### Central Shutdown Path

A focused launcher process-lifecycle module owns Job Object setup and process-tree termination. `launch.py` wraps every post-spawn phase in one `try`/`except KeyboardInterrupt`/`finally` boundary. The shutdown helper sends `CTRL_BREAK_EVENT`, waits up to three seconds, then uses `taskkill /T /F` if the WebUI remains alive. Closing the Job handle in `finally` removes any surviving descendants.

### Batch Lifecycle

Both batch launchers remove their trailing `pause`. Diagnostic pauses remain inside `launch.py` only for startup or crash errors. A successful cancellation returns directly to Windows and closes a double-clicked terminal window.

## Error Handling

- Repeated shutdown calls are idempotent.
- If the WebUI has already exited, shutdown performs no signal or force-kill operation.
- Failure to send `CTRL_BREAK_EVENT` proceeds directly to the bounded wait and force-kill fallback.
- Failure of `taskkill` does not bypass Job handle closure.
- Intentional cancellation does not render a crash diagnostic card.

## Verification

- Standard-library unit tests exercise graceful `CTRL_BREAK_EVENT` shutdown, forced fallback when the child ignores the event, and Job Object kill-on-close behavior for both a child and its descendant.
- A local-launcher smoke test presses `Ctrl+C` during startup and after readiness, then confirms port 7860 is free.
- A public-share smoke test presses `Ctrl+C` after tunnel creation, then confirms both port 7860 and the `frpc` process are gone.
- An abrupt-parent-termination smoke test simulates the `X` button by killing only `launch.py`, then confirms the Job Object terminates the WebUI descendants and releases port 7860.

## Documentation Decision

No ADR is required. The change repairs the existing Smart Launcher lifecycle contract rather than introducing a hard-to-reverse architectural choice. The glossary records the user-visible shutdown meaning; this spec records the implementation design and verification requirements.
