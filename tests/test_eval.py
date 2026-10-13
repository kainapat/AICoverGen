"""Phase 5 tests: audio quality evaluation + alignment stats + runtime measure.

Pure/deterministic; runnable on system python (no model, no soundfile needed
except audio_metrics tests which skip gracefully).
Seams: eval.alignment_stats, eval.measure_runtime, eval.format_metrics_block.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyrics import compare_texts
from lyrics.compare import Mismatch
from lyrics import eval as ev
from lyrics.report import LyricsReport


def rep_with(mismatches, similarity=0.5, gran="word", reliable=True):
    return LyricsReport(
        reference_raw="r", recognized_raw="h", mismatches=mismatches,
        similarity=similarity, timestamp_reliable=reliable,
        timestamp_granularity=gran)


class TestAlignmentStats(unittest.TestCase):
    def test_empty_report(self):
        st = ev.alignment_stats(rep_with([]))
        self.assertEqual((st["total"], st["timed"], st["timed_ratio"]),
                         (0, 0, 1.0))

    def test_counts_and_ratio(self):
        ms = [Mismatch("substitution", "a", "b", 0, 1, 0, 1),
              Mismatch("omission", "c", "", 1, 2, 1, 1)]
        ms[0].start_time, ms[0].end_time = 1.0, 2.0
        st = ev.alignment_stats(rep_with(ms, gran="segment", reliable=False))
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["timed"], 1)
        self.assertAlmostEqual(st["timed_ratio"], 0.5)
        self.assertEqual(st["granularity"], "segment")
        self.assertFalse(st["reliable"])

    def test_confidence_coverage(self):
        ms = [Mismatch("substitution", "a", "b", 0, 1, 0, 1),
              Mismatch("substitution", "c", "d", 1, 2, 1, 2)]
        ms[0].confidence = 0.8
        st = ev.alignment_stats(rep_with(ms))
        self.assertAlmostEqual(st["confidence_coverage"], 0.5)
        self.assertAlmostEqual(st["confidence_mean"], 0.8)

    def test_no_confidence(self):
        st = ev.alignment_stats(rep_with(
            [Mismatch("substitution", "a", "b", 0, 1, 0, 1)]))
        self.assertEqual(st["confidence_coverage"], 0.0)
        self.assertIsNone(st["confidence_mean"])


class TestMeasureRuntime(unittest.TestCase):
    def test_keys_and_ordering(self):
        out, m = ev.measure_runtime(lambda x: x + 1, 41)
        self.assertEqual(out, 42)
        self.assertIn("seconds", m)
        self.assertGreaterEqual(m["seconds"], 0.0)
        self.assertIn("cuda_available", m)
        self.assertIn("cuda_peak_mb", m)
        if not m["cuda_available"]:
            self.assertIsNone(m["cuda_peak_mb"])

    def test_exception_propagates_with_timing(self):
        def boom():
            time.sleep(0.01)
            raise RuntimeError("x")
        with self.assertRaises(RuntimeError):
            ev.measure_runtime(boom)


class TestNoHeavyImports(unittest.TestCase):
    def test_lyrics_has_no_torch_rvc_imports(self):
        # Module level only: guarded lazy imports inside functions are
        # allowed (e.g. eval.measure_runtime probes torch.cuda if present).
        import pathlib
        bad = []
        for p in (pathlib.Path("src") / "lyrics").glob("*.py"):
            txt = p.read_text(encoding="utf-8")
            for line in txt.splitlines():
                if line.startswith("import torch") or line.startswith("from torch") \
                        or "rvc_infer" in line or "fairseq" in line:
                    bad.append(f"{p.name}: {line.strip()}")
        self.assertEqual(bad, [])

    def test_eval_imports_without_torch(self):
        self.assertTrue(hasattr(ev, "alignment_stats"))


class TestMetricsBlock(unittest.TestCase):
    def test_block_mentions_definitions(self):
        info = {"duration_sec": 30.0, "sample_rate": 44100, "channels": 2}
        q = {"peak": 0.5, "rms": 0.1, "clipping_ratio": 0.0,
             "silent_ratio": 0.1, "flags": []}
        st = {"total": 4, "timed": 3, "timed_ratio": 0.75,
              "granularity": "word", "reliable": True,
              "confidence_coverage": 0.5, "confidence_mean": 0.7}
        md = ev.format_metrics_block(info, q, st)
        for token in ("30.0s", "44100", "peak", "rms", "จุดมีเวลา",
                      "ไม่ได้รับประกัน", "naturalness"):
            self.assertIn(token, md)


if __name__ == "__main__":
    unittest.main()
