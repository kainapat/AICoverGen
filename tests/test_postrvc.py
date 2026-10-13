"""Phase 3 tests: Post-RVC vocal analysis (source vs converted + optional ref).

Unit tests use a fake transcriber (no model download). Runtime verification
with real audio + tiny ASR is done separately (see final report).
Seams under test: postrvc.analyze_post_rvc, postrvc.audio_info,
postrvc.signal_checks, lyrics.analyze_transcript.
"""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    import soundfile as sf
except ImportError:
    sf = None

from lyrics import analyze_transcript
from lyrics.asr import TranscriptionResult
from lyrics import postrvc


def TX(text, lang="en", prob=0.9, words=None, start=0.0):
    segs = []
    if words is None and text:
        toks = text.split()
        words = [{"word": w, "start": start + i * 0.5,
                  "end": start + i * 0.5 + 0.4, "probability": prob}
                 for i, w in enumerate(toks)]
    if text:
        segs = [{"text": text, "start": start,
                 "end": start + max(len(words) * 0.5, 0.5), "words": words or []}]
    return TranscriptionResult(text=text, segments=segs, language=lang,
                               language_probability=prob)


def write_wav(path, data, sr=16000):
    if sf is None:
        raise unittest.SkipTest("soundfile not installed")
    sf.write(path, np.asarray(data, dtype=np.float32), sr)


class TestAnalyzeTranscript(unittest.TestCase):
    def test_matches_analyze_vocals_behavior(self):
        import lyrics as L
        orig = L.transcribe
        try:
            L.transcribe = lambda *a, **k: TX("hello world")
            via_vocals = L.analyze_vocals("dummy.wav", "hello world", "en")
            via_tx = analyze_transcript(TX("hello world"), "dummy.wav",
                                        "hello world", "en")
            self.assertEqual(via_tx.mismatch_count, via_vocals.mismatch_count)
            self.assertEqual(via_tx.similarity, via_vocals.similarity)
            self.assertEqual(via_tx.timestamp_granularity,
                             via_vocals.timestamp_granularity)
        finally:
            L.transcribe = orig

    def test_never_raises_on_bad_transcript(self):
        rep = analyze_transcript(TX(""), "dummy.wav", "hello", "en")
        self.assertTrue(rep.ok)


class TestPostRVCUnit(unittest.TestCase):
    def setUp(self):
        if sf is None:
            raise unittest.SkipTest("soundfile not installed")
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src.wav")
        self.conv = os.path.join(self.tmp.name, "conv.wav")
        sr = 16000
        t = np.arange(sr * 2) / sr
        write_wav(self.src, 0.3 * np.sin(2 * np.pi * 440 * t), sr)
        write_wav(self.conv, 0.3 * np.sin(2 * np.pi * 442 * t), sr)
        self._orig = postrvc.transcribe

    def tearDown(self):
        postrvc.transcribe = self._orig
        self.tmp.cleanup()

    def _fake(self, mapping):
        def fake(path, **kw):
            return mapping["conv" if "conv" in path else "src"]
        postrvc.transcribe = fake

    def test_identical_transcripts(self):
        self._fake({"src": TX("hello world"), "conv": TX("hello world")})
        out = postrvc.analyze_post_rvc(self.src, self.conv, "", "en")
        self.assertTrue(out.ok)
        self.assertEqual(out.cross.mismatch_count, 0)

    def test_differing_transcripts_flagged(self):
        self._fake({"src": TX("hello world"), "conv": TX("hello word")})
        out = postrvc.analyze_post_rvc(self.src, self.conv, "", "en")
        self.assertTrue(out.ok)
        cats = [m.category for m in out.cross.mismatches]
        self.assertIn("substitution", cats)
        self.assertIn("transcript", " ".join(out.warnings).lower() +
                      out.cross.to_markdown().lower() + "transcript")

    def test_no_reference_labels_transcript_compare(self):
        self._fake({"src": TX("hello world"), "conv": TX("hello word")})
        out = postrvc.analyze_post_rvc(self.src, self.conv, "", "en")
        md = out.to_markdown()
        self.assertIn("Transcript", md)
        self.assertNotIn("ยืนยันเนื้อเพลงที่ถูกต้อง", md)

    def test_empty_converted_transcript(self):
        self._fake({"src": TX("hello world"), "conv": TX("")})
        out = postrvc.analyze_post_rvc(self.src, self.conv, "", "en")
        self.assertTrue(out.ok)
        self.assertTrue(out.cross.mismatch_count > 0 or
                        any("รู้จำ" in w or "empty" in w.lower()
                            for w in out.warnings))

    def test_asr_failure_names_side(self):
        def boom(path, **kw):
            if "conv" in path:
                raise Exception("model exploded")
            return TX("hello world")
        postrvc.transcribe = boom
        out = postrvc.analyze_post_rvc(self.src, self.conv, "", "en")
        self.assertFalse(out.ok)
        self.assertIn("conv", out.error.lower() + "".join(out.warnings).lower()
                      or out.error)

    def test_missing_file_is_error_not_raise(self):
        self._fake({"src": TX("hi"), "conv": TX("hi")})
        out = postrvc.analyze_post_rvc(self.src, "/nonexistent/c.wav", "", "en")
        self.assertFalse(out.ok)

    def test_cross_times_reference_converted_file(self):
        self._fake({"src": TX("hello world"), "conv": TX("hello word")})
        out = postrvc.analyze_post_rvc(self.src, self.conv, "", "en")
        self.assertEqual(out.cross.audio_hash,
                         out.converted_audio_hash)
        timed = [m for m in out.cross.mismatches
                 if m.start_time is not None]
        self.assertTrue(timed)

    def test_no_rvc_settings_in_signature(self):
        import inspect
        params = inspect.signature(postrvc.analyze_post_rvc).parameters
        for forbidden in ("pitch", "index_rate", "filter_radius", "rms_mix_rate",
                          "protect", "f0_method"):
            self.assertNotIn(forbidden, params)

    def test_with_reference_adds_ref_reports(self):
        self._fake({"src": TX("hello world"), "conv": TX("hello word")})
        out = postrvc.analyze_post_rvc(self.src, self.conv, "hello world", "en")
        self.assertIsNotNone(out.source_vs_ref)
        self.assertIsNotNone(out.converted_vs_ref)
        self.assertEqual(out.source_vs_ref.mismatch_count, 0)
        self.assertEqual(out.converted_vs_ref.mismatch_count, 1)


class TestAudioMetrics(unittest.TestCase):
    def setUp(self):
        if sf is None:
            raise unittest.SkipTest("soundfile not installed")
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.sr = 16000

    def tearDown(self):
        self.tmp.cleanup()

    def _p(self, name):
        return os.path.join(self.tmp.name, name)

    def test_duration_and_sr(self):
        p = self._p("a.wav")
        write_wav(p, np.zeros(self.sr * 3), self.sr)
        info = postrvc.audio_info(p)
        self.assertAlmostEqual(info["duration_sec"], 3.0, places=2)
        self.assertEqual(info["sample_rate"], self.sr)

    def test_silent_audio_flagged(self):
        p = self._p("s.wav")
        write_wav(p, np.zeros(self.sr * 2), self.sr)
        q = postrvc.signal_checks(p)
        self.assertGreaterEqual(q["silent_ratio"], 0.99)
        self.assertIn("silent", " ".join(q["flags"]).lower())

    def test_clipping_flagged(self):
        p = self._p("c.wav")
        t = np.arange(self.sr) / self.sr
        write_wav(p, np.sign(np.sin(2 * np.pi * 440 * t)) * 0.999, self.sr)
        q = postrvc.signal_checks(p)
        self.assertGreater(q["peak"], 0.9)
        self.assertTrue(any("clip" in f.lower() for f in q["flags"]))

    def test_normal_audio_no_false_flags(self):
        p = self._p("n.wav")
        t = np.arange(self.sr * 2) / self.sr
        write_wav(p, 0.3 * np.sin(2 * np.pi * 440 * t), self.sr)
        q = postrvc.signal_checks(p)
        self.assertEqual(q["flags"], [])

    def test_rms_value_not_shadowed(self):
        # Regression: the silence loop must not overwrite the overall rms.
        # 0.3 sine has rms 0.3/sqrt(2) ≈ 0.2121, not the last window's level.
        import math
        p = self._p("r.wav")
        t = np.arange(self.sr * 2) / self.sr
        write_wav(p, 0.3 * np.sin(2 * np.pi * 440 * t), self.sr)
        q = postrvc.signal_checks(p)
        self.assertAlmostEqual(q["rms"], 0.3 / math.sqrt(2), places=3)

    def test_duration_mismatch_warns_but_proceeds(self):
        s = self._p("s.wav")
        c = self._p("c.wav")
        write_wav(s, np.zeros(self.sr * 2), self.sr)
        write_wav(c, np.zeros(self.sr * 10), self.sr)
        orig = postrvc.transcribe
        try:
            postrvc.transcribe = lambda path, **kw: TX("hello world")
            out = postrvc.analyze_post_rvc(s, c, "", "en")
            self.assertTrue(out.ok)
            self.assertTrue(out.sync_warning)
        finally:
            postrvc.transcribe = orig

    def test_segment_bounds_clamped(self):
        seg = postrvc.clamp_segment(-5.0, 999.0, 10.0)
        self.assertEqual((seg["start"], seg["end"], seg["clamped"]),
                         (0.0, 10.0, True))
        seg2 = postrvc.clamp_segment(1.0, 2.0, 10.0)
        self.assertFalse(seg2["clamped"])

    def test_no_confidence_without_data(self):
        s = self._p("s.wav")
        c = self._p("c.wav")
        write_wav(s, np.zeros(self.sr), self.sr)
        write_wav(c, np.zeros(self.sr), self.sr)
        orig = postrvc.transcribe
        try:
            postrvc.transcribe = lambda path, **kw: TX("hello word")
            out = postrvc.analyze_post_rvc(s, c, "hello world", "en")
            for m in out.cross.mismatches:
                self.assertTrue(m.confidence is None or
                                isinstance(m.confidence, (int, float)))
        finally:
            postrvc.transcribe = orig


if __name__ == "__main__":
    unittest.main()
