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
