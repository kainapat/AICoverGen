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
            "while True:\n"
            "    time.sleep(0.05)\n"
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
