# Error Diagnostic Card and Traceback Buffer Drainer

We implement state-aware traceback accumulation and child-process pipe draining in `launch.py`, ensuring full exception stacktraces are captured and displayed inside a high-visibility Cyberpunk Error Diagnostic Card rather than being truncated upon process termination.

**Context & Problem:**
When the Gradio WebUI worker crashes or raises an unhandled exception, `launch.py`'s background reader thread (`daemon=True`) was previously terminated abruptly by Python when `proc.wait()` unblocked in the main thread. This caused stacktraces to be cut off after the first line (`Traceback (most recent call last):`), leaving users and developers with no visible diagnostic information (file path, line number, or error type). Furthermore, lines following the first traceback line were treated as generic logs and rendered in dim gray text without visual distinction.

**Considered Options:**
- Rely solely on `webui.log` file without terminal rendering — rejected: users expect immediate in-terminal feedback when double-clicking `.bat` without digging into log files.
- Unbuffered raw standard error dump — rejected: fails to fit the Cyberpunk UI aesthetic and still risks abrupt termination if child process pipes are not explicitly drained before exiting.
- Error Diagnostic Card with Traceback Buffer Drainer — accepted: maintains full terminal aesthetic, captures the complete multi-line traceback into a red/amber alert card with human-readable hints, and pauses for user confirmation (`Press Enter to exit`) upon non-zero exit codes.

**Consequences:**
Child process pipes are guaranteed to be drained completely upon crash. Stacktrace blocks are parsed as single cohesive diagnostic units, rendering error details prominently. The terminal will never close automatically on failure, giving users ample time to inspect or copy error details.
