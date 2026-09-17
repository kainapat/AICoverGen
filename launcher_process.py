import ctypes
import signal
import subprocess
import sys
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
