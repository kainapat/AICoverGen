# Reliable Launcher Shutdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable reliable cancellation for both `run_aicovergen.bat` and `run_aicovergen_share.bat` on `Ctrl+C` and the window close button (`X`) by isolating process-tree shutdown inside a dedicated Windows Job Object helper, wiring all launcher lifecycle phases into one guarded termination path, and removing the blocking batch `pause`.

**Architecture:** A new `launcher_process.py` module encapsulates Windows `ctypes` Job Object management (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) and process-tree termination. `launch.py` creates a child process group for `src/webui.py`, binds the process tree to the Job Object, and executes startup, tunnel negotiation, and the steady-state listener inside one unified `try`/`except KeyboardInterrupt`/`finally` block. `run_aicovergen.bat` and `run_aicovergen_share.bat` execute `launch.py` directly without a trailing `pause`.

**Tech Stack:** Python 3.10.11 standard library (`ctypes`, `subprocess`, `unittest`, `signal`, `threading`), Windows Console/Job Object Win32 APIs (`kernel32`), Windows batch (`cmd.exe`).

## Global Constraints

- Must work on Windows 11 with the project virtual environment at `.\.venv\Scripts\python.exe`.
- Must not add third-party dependencies (`psutil` or `pywin32` are prohibited; standard library only).
- Must preserve port 7860 availability immediately after cancellation.
- Must terminate descendant processes (`ffmpeg.exe`, `sox.exe`, `frpc_windows_amd64_v0.3.exe`, and child `python.exe` workers).
- Must run automated regression tests with standard library `unittest`: `.\.venv\Scripts\python.exe -m unittest tests/test_launcher_process.py -v`.
- Must preserve existing IBM Carbon theme formatting and diagnostic crash pause behavior for actual errors.

---

### Task 1: Create Windows Process Lifecycle Helper with Automated Tests

**Files:**
- Create: `launcher_process.py`
- Test: `tests/test_launcher_process.py`

**Interfaces:**
- Consumes: `ctypes`, `subprocess`, `sys`, `time`
- Produces:
  - `class WindowsJobManager()`:
    - `bind_process(proc: subprocess.Popen) -> None`
    - `close() -> None`
  - `terminate_process_tree(proc: subprocess.Popen, timeout: float = 3.0) -> None`
  - `spawn_supervised_process(cmd: list[str], cwd: str, env: dict[str, str], logfile: str) -> tuple[subprocess.Popen, WindowsJobManager, threading.Thread]`

- [ ] **Step 1: Write the failing tests for process tree termination and Job Object binding**

Create `tests/test_launcher_process.py`:

```python
import os
import subprocess
import sys
import time
import unittest

from launcher_process import WindowsJobManager, terminate_process_tree


class TestLauncherProcess(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows-only Job Object tests")
    def test_job_manager_kills_child_on_close(self):
        job = WindowsJobManager()
        cmd = [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ]
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            job.bind_process(proc)
            self.assertIsNone(proc.poll(), "Child process should be running initially")
        finally:
            job.close()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        self.assertIsNotNone(
            proc.poll(),
            "Process bound to Job Object must terminate automatically when Job closes",
        )

    @unittest.skipUnless(sys.platform == "win32", "Windows-only termination tests")
    def test_terminate_process_tree_graceful_break(self):
        code = (
            "import signal, sys, time\n"
            "def handler(sig, frame):\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGBREAK, handler)\n"
            "time.sleep(60)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            time.sleep(0.5)
            self.assertIsNone(proc.poll())
            terminate_process_tree(proc, timeout=2.0)
            self.assertIsNotNone(proc.poll())
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()

    @unittest.skipUnless(sys.platform == "win32", "Windows-only force termination tests")
    def test_terminate_process_tree_forces_kill_on_unresponsive_child(self):
        code = (
            "import signal, time\n"
            "signal.signal(signal.SIGBREAK, signal.SIG_IGN)\n"
            "while True:\n"
            "    time.sleep(1)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            time.sleep(0.5)
            self.assertIsNone(proc.poll())
            terminate_process_tree(proc, timeout=1.0)
            self.assertIsNotNone(proc.poll())
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails before implementation**

Run: `.\.venv\Scripts\python.exe -m unittest tests/test_launcher_process.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_process'`

- [ ] **Step 3: Implement minimal `launcher_process.py`**

Create `launcher_process.py`:

```python
import ctypes
import os
import signal
import subprocess
import sys
import threading
import time

if sys.platform == "win32":
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    JobObjectBasicLimitInformation = 2
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    PROCESS_ALL_ACCESS = 0x001F0FFF

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoCounters", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]

    CreateJobObjectW = kernel32.CreateJobObjectW
    CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    CreateJobObjectW.restype = wintypes.HANDLE

    SetInformationJobObject = kernel32.SetInformationJobObject
    SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    SetInformationJobObject.restype = wintypes.BOOL

    AssignProcessToJobObject = kernel32.AssignProcessToJobObject
    AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    AssignProcessToJobObject.restype = wintypes.BOOL

    OpenProcess = kernel32.OpenProcess
    OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    OpenProcess.restype = wintypes.HANDLE

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL


class WindowsJobManager:
    def __init__(self) -> None:
        self._handle = None
        if sys.platform != "win32":
            return

        handle = CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        success = SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not success:
            err = ctypes.get_last_error()
            CloseHandle(handle)
            raise ctypes.WinError(err)

        self._handle = handle

    def bind_process(self, proc: subprocess.Popen) -> None:
        if sys.platform != "win32" or not self._handle or proc.poll() is not None:
            return

        proc_handle = OpenProcess(PROCESS_ALL_ACCESS, False, proc.pid)
        if not proc_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            assigned = AssignProcessToJobObject(self._handle, proc_handle)
            if not assigned:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            CloseHandle(proc_handle)

    def close(self) -> None:
        if sys.platform == "win32" and self._handle:
            CloseHandle(self._handle)
            self._handle = None


def terminate_process_tree(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception:
            pass

    deadline = time.time() + max(0.2, timeout)
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    if proc.poll() is None and sys.platform == "win32":
        subprocess.run(
            f"taskkill /T /F /PID {proc.pid}",
            capture_output=True,
            shell=True,
        )

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m unittest tests/test_launcher_process.py -v`
Expected: `Ran 3 tests in ...s` / `OK`

- [ ] **Step 5: Commit helper and unit tests**

```bash
git add launcher_process.py tests/test_launcher_process.py
git commit -m "feat(launcher): add Windows Job Object and process tree termination helper"
```

---

### Task 2: Integrate Central Shutdown and Process Group into `launch.py`

**Files:**
- Modify: `launch.py:440-570`
- Test: `tests/test_launch_wiring.py`

**Interfaces:**
- Consumes: `launcher_process.WindowsJobManager`, `launcher_process.terminate_process_tree`
- Produces: `launch.py:main()` guarded by full lifecycle termination boundary

- [ ] **Step 1: Write failing wiring test for clean shutdown execution**

Create `tests/test_launch_wiring.py`:

```python
import subprocess
import sys
import unittest


class TestLaunchWiring(unittest.TestCase):
    def test_launch_module_exposes_shutdown_contract(self):
        import launch
        self.assertTrue(hasattr(launch, "shutdown_server"))
        self.assertTrue(callable(launch.shutdown_server))

    def test_launch_help_does_not_crash(self):
        result = subprocess.run(
            [sys.executable, "launch.py", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("AICoverGen", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run wiring test to verify it fails before edits**

Run: `.\.venv\Scripts\python.exe -m unittest tests/test_launch_wiring.py -v`
Expected: FAIL with `AssertionError: False is not true` (`hasattr(launch, "shutdown_server")`)

- [ ] **Step 3: Wire `launch.py` to use Job Object and unified shutdown**

Update `launch.py`:

1. Import helpers at top of `launch.py`:
```python
from launcher_process import WindowsJobManager, terminate_process_tree
```

2. Add dedicated `shutdown_server(proc, job_manager)` function:
```python
def shutdown_server(proc, job_manager=None):
    if proc is None:
        return
    print()
    cprint("  🛑 Terminating WebUI server gracefully...", "amber")
    try:
        terminate_process_tree(proc, timeout=3.0)
    finally:
        if job_manager:
            job_manager.close()
    cprint("  ✔ Server stopped cleanly.", "emerald")
```

3. Update `main()` in `launch.py`:
- Use `subprocess.CREATE_NEW_PROCESS_GROUP` alongside `subprocess.CREATE_NO_WINDOW`.
- Instantiate `job_manager = WindowsJobManager()`.
- Call `job_manager.bind_process(proc)`.
- Enclose everything from socket polling through `proc.wait()` in:
```python
    proc = None
    job_manager = None
    try:
        job_manager = WindowsJobManager()
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=BASE_DIR,
            env=child_env,
            creationflags=flags,
        )
        job_manager.bind_process(proc)
        ...
    except KeyboardInterrupt:
        shutdown_server(proc, job_manager)
        return
    finally:
        if job_manager:
            job_manager.close()
```

- [ ] **Step 4: Run wiring tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m unittest tests/test_launch_wiring.py -v`
Expected: `Ran 2 tests in ...s` / `OK`

- [ ] **Step 5: Run full test suite**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`
Expected: `Ran 5 tests in ...s` / `OK`

- [ ] **Step 6: Commit `launch.py` integration**

```bash
git add launch.py tests/test_launch_wiring.py
git commit -m "feat(launcher): integrate Windows Job Object and central shutdown into launch.py"
```

---

### Task 3: Remove Blocking `pause` from Both Batch Launchers

**Files:**
- Modify: `run_aicovergen.bat:1-11`
- Modify: `run_aicovergen_share.bat:1-11`
- Test: `tests/test_batch_launchers.py`

**Interfaces:**
- Consumes: `run_aicovergen.bat`, `run_aicovergen_share.bat`
- Produces: Batch files that terminate immediately upon `launch.py` exit without asking user to press a key.

- [ ] **Step 1: Write test checking batch files contain no trailing `pause`**

Create `tests/test_batch_launchers.py`:

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TestBatchLaunchers(unittest.TestCase):
    def test_run_aicovergen_has_no_pause(self):
        content = (ROOT / "run_aicovergen.bat").read_text(encoding="utf-8").strip().splitlines()
        self.assertNotIn("pause", [line.strip().lower() for line in content])
        self.assertTrue(any("launch.py" in line for line in content))

    def test_run_aicovergen_share_has_no_pause(self):
        content = (ROOT / "run_aicovergen_share.bat").read_text(encoding="utf-8").strip().splitlines()
        self.assertNotIn("pause", [line.strip().lower() for line in content])
        self.assertTrue(any("launch.py --share" in line for line in content))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails on existing files**

Run: `.\.venv\Scripts\python.exe -m unittest tests/test_batch_launchers.py -v`
Expected: FAIL with `AssertionError: 'pause' unexpectedly found`

- [ ] **Step 3: Remove `pause` from `run_aicovergen.bat` and `run_aicovergen_share.bat`**

Update `run_aicovergen.bat`:
```bat
@echo off
cd /d "%~dp0"
title AICoverGen - Neural Voice Engine
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>&1
set HF_HOME=D:\AI_Cache\huggingface
set TORCH_HOME=D:\AI_Cache\torch
set PIP_CACHE_DIR=D:\AI_Cache\pip
set UV_CACHE_DIR=D:\AI_Cache\uv
.\.venv\Scripts\python.exe launch.py
```

Update `run_aicovergen_share.bat`:
```bat
@echo off
cd /d "%~dp0"
title AICoverGen - Neural Voice Engine (Public Share Mode)
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>&1
set HF_HOME=D:\AI_Cache\huggingface
set TORCH_HOME=D:\AI_Cache\torch
set PIP_CACHE_DIR=D:\AI_Cache\pip
set UV_CACHE_DIR=D:\AI_Cache\uv
.\.venv\Scripts\python.exe launch.py --share
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m unittest tests/test_batch_launchers.py -v`
Expected: `Ran 2 tests in ...s` / `OK`

- [ ] **Step 5: Commit batch file changes**

```bash
git add run_aicovergen.bat run_aicovergen_share.bat tests/test_batch_launchers.py
git commit -m "fix(launcher): remove trailing pause so shutdown closes batch window immediately"
```

---

### Task 4: End-to-End Verification of `Ctrl+C` and Window Close Semantics

**Files:**
- Test: `tests/test_shutdown_e2e.py`
- Modify: `docs/superpowers/specs/2026-09-17-reliable-launcher-shutdown-design.md` (record verification results)

**Interfaces:**
- Consumes: `run_aicovergen.bat`, `run_aicovergen_share.bat`, `launch.py`
- Produces: Verified process cleanup with port 7860 freed under simulated interrupt and simulated close button.

- [ ] **Step 1: Write automated e2e test verifying interrupt and parent termination**

Create `tests/test_shutdown_e2e.py`:

```python
import os
import signal
import socket
import subprocess
import sys
import time
import unittest


def is_port_open(port=7860):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        res = s.connect_ex(("127.0.0.1", port))
        return res == 0
    finally:
        s.close()


class TestShutdownE2E(unittest.TestCase):
    def test_parent_termination_cleans_child_via_job_object(self):
        # Starts launch.py in isolated mode and abruptly terminates parent
        proc = subprocess.Popen(
            [sys.executable, "launch.py"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # Wait until local socket becomes active or max 30 seconds
            deadline = time.time() + 30.0
            while time.time() < deadline:
                if is_port_open(7860):
                    break
                time.sleep(0.5)

            self.assertTrue(is_port_open(7860), "WebUI should be listening on 7860")

            # Simulate clicking 'X' by killing only the launcher process
            subprocess.run(f"taskkill /F /PID {proc.pid}", capture_output=True, shell=True)

            # Confirm port 7860 releases within 5 seconds
            cleanup_deadline = time.time() + 5.0
            freed = False
            while time.time() < cleanup_deadline:
                if not is_port_open(7860):
                    freed = True
                    break
                time.sleep(0.5)

            self.assertTrue(freed, "Port 7860 must be released after parent window closure")
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run full regression test suite**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`
Expected: All tests pass (`OK`).

- [ ] **Step 3: Run live smoke test on `run_aicovergen.bat` and interrupt via Hub**

1. Start `run_aicovergen.bat` via hub.
2. Verify ready state on port 7860.
3. Send interrupt signal (`SIGINT` or `CTRL_C`).
4. Verify process terminates and port 7860 is released.

- [ ] **Step 4: Commit test and documentation updates**

```bash
git add tests/test_shutdown_e2e.py docs/superpowers/specs/2026-09-17-reliable-launcher-shutdown-design.md
git commit -m "test(launcher): add end-to-end shutdown tests for Ctrl+C and close button"
```
