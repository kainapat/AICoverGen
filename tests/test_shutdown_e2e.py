import os
import signal
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launch import shutdown_server
from launcher_process import WindowsJobManager, terminate_process_tree


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def wait_for_port_status(port: int, open_target: bool, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(port) == open_target:
            return True
        time.sleep(0.05)
    return is_port_open(port) == open_target


class TestShutdownE2E(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object tests require win32")
    def test_job_object_cleans_child_socket_on_abrupt_parent_exit(self):
        # Simulates clicking 'X' (window close):
        # A parent process binds a child listening server to WindowsJobManager, then the parent
        # is abruptly killed (simulating Windows destroying the console host or closing the window).
        # Windows Job Object must immediately terminate the child process and release its listening port.
        child_lines = [
            "import socket, sys, time",
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
            "s.bind(('127.0.0.1', 0))",
            "s.listen(1)",
            "port = s.getsockname()[1]",
            "sys.stdout.write(f'READY:{port}\\n')",
            "sys.stdout.flush()",
            "while True:",
            "    time.sleep(0.5)",
        ]
        child_code = "\n".join(child_lines)

        parent_lines = [
            "import subprocess, sys, time",
            "from launcher_process import WindowsJobManager",
            f"child_code = {repr(child_code)}",
            "child = subprocess.Popen([sys.executable, '-u', '-c', child_code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)",
            "job = WindowsJobManager()",
            "job.bind_process(child)",
            "line = child.stdout.readline()",
            "port = int(line.strip().split(':')[1])",
            "sys.stdout.write(f'PORT:{port}:CHILD:{child.pid}\\n')",
            "sys.stdout.flush()",
            "while True:",
            "    time.sleep(1)",
        ]
        parent_code = "\n".join(parent_lines)

        parent = subprocess.Popen(
            [sys.executable, "-u", "-c", parent_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        try:
            line = parent.stdout.readline()
            self.assertTrue(line.startswith("PORT:"), f"Expected PORT header, got: {line}")
            parts = line.strip().split(":")
            port = int(parts[1])
            child_pid = int(parts[3])

            self.assertTrue(wait_for_port_status(port, open_target=True, timeout=3.0), f"Port {port} should be open")

            # Abruptly kill parent process (simulating 'X' button or TerminateProcess)
            parent.kill()
            parent.wait(timeout=2.0)

            # Child process must be killed and port freed within 3 seconds
            port_freed = wait_for_port_status(port, open_target=False, timeout=3.0)
            self.assertTrue(port_freed, f"Port {port} must be freed after parent abrupt termination")
        finally:
            if parent.stdout:
                parent.stdout.close()
            if parent.stderr:
                parent.stderr.close()
            if parent.poll() is None:
                parent.kill()

    @unittest.skipUnless(sys.platform == "win32", "Windows process termination tests require win32")
    def test_ctrl_break_escalation_frees_socket(self):
        # Tests that when an uncooperative child ignoring SIGBREAK receives terminate_process_tree,
        # the escalation to taskkill terminates the process and frees the socket within 3 seconds.
        child_lines = [
            "import signal, socket, sys, time",
            "signal.signal(signal.SIGBREAK, signal.SIG_IGN)",
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
            "s.bind(('127.0.0.1', 0))",
            "s.listen(1)",
            "port = s.getsockname()[1]",
            "sys.stdout.write(f'READY:{port}\\n')",
            "sys.stdout.flush()",
            "while True:",
            "    time.sleep(0.5)",
        ]
        child_code = "\n".join(child_lines)

        child = subprocess.Popen(
            [sys.executable, "-u", "-c", child_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            cwd=str(REPO_ROOT),
        )
        try:
            line = child.stdout.readline()
            self.assertTrue(line.startswith("READY:"), f"Expected READY header, got: {line}")
            port = int(line.strip().split(":")[1])

            self.assertTrue(wait_for_port_status(port, open_target=True, timeout=3.0), f"Port {port} should be open")

            # Terminate with timeout=1.5; escalation to taskkill should kill process and free socket in < 3.0s
            start = time.time()
            terminate_process_tree(child, timeout=1.5)
            elapsed = time.time() - start

            self.assertLess(elapsed, 3.0, f"Escalation took {elapsed:.2f}s, expected < 3.0s")
            self.assertIsNotNone(child.poll(), "Child process should be terminated after escalation")
            self.assertTrue(wait_for_port_status(port, open_target=False, timeout=1.5), f"Port {port} should be freed")
        finally:
            if child.stdout:
                child.stdout.close()
            if child.stderr:
                child.stderr.close()
            if child.poll() is None:
                child.kill()

    @unittest.skipUnless(sys.platform == "win32", "Windows Ctrl+C tests require win32")
    def test_shutdown_server_ctrl_c_graceful_break_frees_socket(self):
        # Tests Ctrl+C semantics: shutdown_server gracefully terminates listening child
        # and cleans up the process tree and job object.
        child_lines = [
            "import signal, socket, sys, time",
            "def on_break(sig, frame):",
            "    sys.exit(0)",
            "signal.signal(signal.SIGBREAK, on_break)",
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
            "s.bind(('127.0.0.1', 0))",
            "s.listen(1)",
            "port = s.getsockname()[1]",
            "sys.stdout.write(f'READY:{port}\\n')",
            "sys.stdout.flush()",
            "while True:",
            "    time.sleep(0.5)",
        ]
        child_code = "\n".join(child_lines)

        child = subprocess.Popen(
            [sys.executable, "-u", "-c", child_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            cwd=str(REPO_ROOT),
        )
        job = WindowsJobManager()
        try:
            job.bind_process(child)
            line = child.stdout.readline()
            self.assertTrue(line.startswith("READY:"), f"Expected READY header, got: {line}")
            port = int(line.strip().split(":")[1])

            self.assertTrue(wait_for_port_status(port, open_target=True, timeout=3.0), f"Port {port} should be open")

            start = time.time()
            shutdown_server(child, job)
            elapsed = time.time() - start

            self.assertLess(elapsed, 2.0, f"Graceful shutdown took {elapsed:.2f}s, expected < 2.0s")
            self.assertEqual(child.poll(), 0, "Child should exit with return code 0 on graceful break")
            self.assertTrue(wait_for_port_status(port, open_target=False, timeout=1.0), f"Port {port} should be freed")
        finally:
            if child.stdout:
                child.stdout.close()
            if child.stderr:
                child.stderr.close()
            if child.poll() is None:
                child.kill()
            job.close()


if __name__ == "__main__":
    unittest.main()
