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

### Verified Automated Test Results

All 10 tests across the test suite execute deterministically via standard library `unittest`:

```text
test_run_aicovergen_has_no_pause (test_batch_launchers.TestBatchLaunchers) ... ok
test_run_aicovergen_share_has_no_pause (test_batch_launchers.TestBatchLaunchers) ... ok
test_launch_help_does_not_crash (test_launch_wiring.TestLaunchWiring) ... ok
test_launch_module_exposes_shutdown_contract (test_launch_wiring.TestLaunchWiring) ... ok
test_job_manager_kills_child_on_close (test_launcher_process.TestLauncherProcess) ... ok
test_terminate_process_tree_forces_kill_on_unresponsive_child (test_launcher_process.TestLauncherProcess) ... ok
test_terminate_process_tree_graceful_break (test_launcher_process.TestLauncherProcess) ... ok
test_ctrl_break_escalation_frees_socket (test_shutdown_e2e.TestShutdownE2E) ... ok
test_job_object_cleans_child_socket_on_abrupt_parent_exit (test_shutdown_e2e.TestShutdownE2E) ... ok
test_shutdown_server_ctrl_c_graceful_break_frees_socket (test_shutdown_e2e.TestShutdownE2E) ... ok

----------------------------------------------------------------------
Ran 10 tests in 6.5s

OK
```

Specific verification coverage:
1. **Window Close Button ('X') Semantics**: `test_job_object_cleans_child_socket_on_abrupt_parent_exit` verifies that abrupt termination of a parent process (without executing `job.close()` or Python `finally` blocks) triggers Windows Job Object kernel-level termination of the child server and immediately releases the socket.
2. **Ctrl+C Interrupt Semantics & Graceful Break**: `test_shutdown_server_ctrl_c_graceful_break_frees_socket` verifies that `shutdown_server` sends `CTRL_BREAK_EVENT`, child server exits with return code 0, and socket releases cleanly in under 1 second.
3. **Process Tree Escalation**: `test_ctrl_break_escalation_frees_socket` verifies that if a child ignores `SIGBREAK`, `terminate_process_tree` escalates to `taskkill /T /F` and frees the socket in under 3 seconds.
4. **Batch Window Immediate Close**: `test_batch_launchers` verifies no trailing `pause` exists in `run_aicovergen.bat` or `run_aicovergen_share.bat`.
## Documentation Decision

No ADR is required. The change repairs the existing Smart Launcher lifecycle contract rather than introducing a hard-to-reverse architectural choice. The glossary records the user-visible shutdown meaning; this spec records the implementation design and verification requirements.
