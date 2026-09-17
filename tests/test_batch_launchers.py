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
