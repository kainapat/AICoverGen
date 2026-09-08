# Suppress Windows Asyncio Connection Reset Noise (WinError 10054)

We silence harmless TCP connection reset exceptions (`ConnectionResetError: [WinError 10054]`) within Python's Windows `_ProactorBasePipeTransport` and filter them from `launch.py`'s Error Diagnostic Card.

**Context & Problem:**
On Windows, when a web client abruptly terminates a connection — such as pressing F5 to refresh the browser, closing the browser tab, or when a download manager drops an idle socket — the operating system delivers a TCP RST packet. When Python's `asyncio` Proactor event loop subsequently invokes `_ProactorBasePipeTransport._call_connection_lost()`, it attempts `socket.shutdown(socket.SHUT_RDWR)` on the already-reset socket. This raises:
```text
ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host
```
While this event is completely benign and does not affect server operation or the AI conversion pipeline, `asyncio` logs the full multi-line stacktrace to standard error. In turn, `launch.py`’s traceback detection logic intercepted this log as a fatal pipeline failure and rendered a red `EXCEPTION DIAGNOSTIC DETECTED` card, alarming the user needlessly.

**Considered Options:**
- Ignore without code changes — rejected: false-positive error cards severely degrade user experience and create anxiety during routine browser refreshes.
- Filter only in `launch.py` — partially effective: hides the terminal card, but raw log lines still pollute `webui.log` and terminal stdout.
- Two-Tier Silence: Monkey-patch `_call_connection_lost` in `src/webui.py` to catch `(ConnectionResetError, OSError)` on socket shutdown + filter in `launch.py` — accepted: prevents the exception from being logged at the source while ensuring the launcher never flags client disconnects as pipeline crashes.

**Consequences:**
Normal browser refreshes and tab closures no longer trigger noisy stacktraces or false-positive error diagnostic cards. Legitimate pipeline errors remain fully monitored and reported as usual.
