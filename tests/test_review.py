"""Phase 4 tests: lyric error review & user correction workflow.

Deterministic unit tests (no model). Audio-bound checks that need soundfile
are skipped when it is unavailable; they run on .venv.
Seams: review.build_review/start_review/apply_correction/confirm_correction/
revert_correction/preview_corrected_text/recheck_reviewed/save_session/
load_session/validate_item_audio/check_stale.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    import soundfile as sf  # noqa: F401
    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False

import numpy as np

from lyrics import analyze_transcript, error_report
from lyrics.asr import TranscriptionResult
from lyrics import review


def TX(text, lang="en", prob=0.9):
    toks = text.split()
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4,
              "probability": prob} for i, w in enumerate(toks)]
    segs = [{"text": text, "start": 0.0, "end": len(toks) * 0.5,
             "words": words}] if text else []
    return TranscriptionResult(text=text, segments=segs, language=lang,
                               language_probability=prob)


def session_for(ref, hyp, lang="en", audio="dummy.wav"):
    rep = analyze_transcript(TX(hyp, lang), audio, ref, lang)
    return review.build_review(rep, audio)


class TestClassification(unittest.TestCase):
    def test_match_session(self):
        s = session_for("hello world", "hello world")
        self.assertEqual(s.status, "MATCH")
        self.assertEqual(s.items, [])

    def test_substitution_is_possible_mismatch(self):
        s = session_for("hello world", "hello word")
        self.assertEqual(s.status, "HAS_ITEMS")
        self.assertEqual(s.items[0].status, "POSSIBLE_MISMATCH")
        self.assertEqual(s.items[0].kind, "substitution")

    def test_omission_is_missing_text(self):
        s = session_for("a b c d", "a b d")
        kinds = {(i.kind, i.status) for i in s.items}
        self.assertIn(("omission", "MISSING_TEXT"), kinds)

    def test_insertion_is_extra_text(self):
        s = session_for("a b d", "a b c d")
        kinds = {(i.kind, i.status) for i in s.items}
        self.assertIn(("insertion", "EXTRA_TEXT"), kinds)

    def test_omission_without_hyp_span_keeps_kind(self):
        # Empty hyp span = nothing to place in time; the kind status stays
        # (ALIGNMENT_UNRELIABLE is only for placeable spans without time).
        s = session_for("a b c d", "a b d")
        om = [i for i in s.items if i.kind == "omission"][0]
        self.assertEqual(om.status, "MISSING_TEXT")
        self.assertIsNone(om.start_time)

    def test_thai_spaceless_reviewable(self):
        s = session_for("ฉันรักเธอมาก", "ฉันรักเธอ", "th")
        self.assertEqual(s.status, "HAS_ITEMS")
        self.assertTrue(all(i.status in review.REVIEW_STATUSES for i in s.items))

    def test_missing_time_is_unreliable(self):
        s = session_for("hello world", "hello word")
        item = s.items[0]
        item.start_time = None
        item.end_time = None
        s2 = session_for("hello world", "hello word")
        s2.items[0].start_time = None
        s2.items[0].end_time = None
        fixed = review.refresh_time_status(s2)
        self.assertEqual(fixed.items[0].status, "ALIGNMENT_UNRELIABLE")
        self.assertIn("เวลา", fixed.items[0].reason)
        _ = item

    def test_no_reference_session(self):
        rep = analyze_transcript(TX("hello world"), "dummy.wav", "", "en")
        s = review.build_review(rep, "dummy.wav")
        self.assertEqual(s.status, "NO_REFERENCE")
        self.assertFalse(s.complete)

    def test_asr_failed_session(self):
        rep = error_report("boom")
        s = review.build_review(rep, "dummy.wav")
        self.assertEqual(s.status, "ASR_FAILED")
        self.assertEqual(s.items, [])

    def test_item_carries_evidence(self):
        s = session_for("hello world", "hello word")
        i = s.items[0]
        self.assertTrue(i.ref_text)
        self.assertTrue(i.hyp_text)
        self.assertIsNotNone(i.start_time)
        self.assertIn(i.confidence_source, ("asr-word-mean", "none"))


class TestCorrectionWorkflow(unittest.TestCase):
    def test_apply_and_preview(self):
        s = session_for("hello world", "hello word")
        item_id = s.items[0].id
        review.apply_correction(s, item_id, "world", actor="user")
        self.assertEqual(s.items[0].corrected_text, "world")
        self.assertIn("world", review.preview_corrected_text(s))
        self.assertEqual(s.items[0].history[-1]["actor"], "user")

    def test_original_transcript_untouched(self):
        s = session_for("hello world", "hello word")
        orig = s.original_transcript
        review.apply_correction(s, s.items[0].id, "WORLD")
        review.confirm_correction(s, s.items[0].id)
        self.assertEqual(s.original_transcript, orig)
        self.assertIn("hello word", s.original_transcript)

    def test_confirm_marks_reviewed(self):
        s = session_for("hello world", "hello word")
        self.assertFalse(s.items[0].reviewed)
        review.confirm_correction(s, s.items[0].id, actor="user")
        self.assertTrue(s.items[0].reviewed)

    def test_revert_restores_previous(self):
        s = session_for("hello world", "hello word")
        review.apply_correction(s, s.items[0].id, "WORLD")
        review.revert_correction(s, s.items[0].id)
        self.assertIsNone(s.items[0].corrected_text)
        self.assertFalse(s.items[0].reviewed)

    def test_revert_without_history_raises(self):
        s = session_for("hello world", "hello word")
        with self.assertRaises(ValueError):
            review.revert_correction(s, s.items[0].id)

    def test_unknown_item_raises(self):
        s = session_for("hello world", "hello word")
        with self.assertRaises(ValueError):
            review.apply_correction(s, "nope", "x")

    def test_recheck_after_correction(self):
        s = session_for("hello world", "hello word")
        review.apply_correction(s, s.items[0].id, "world")
        out = review.recheck_reviewed(s, "en")
        self.assertEqual(len(out.mismatches), 0)

    def test_reference_never_assumed_correct(self):
        # Correcting hyp toward a WRONG ref is allowed; correcting the ref
        # itself is a separate explicit call, never silent.
        s = session_for("hello word", "hello world")
        self.assertTrue(s.items)
        with self.assertRaises(ValueError):
            review.apply_correction(s, s.items[0].id, 123)

    def test_save_load_roundtrip(self):
        import tempfile
        s = session_for("hello world", "hello word")
        review.apply_correction(s, s.items[0].id, "world", actor="user")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            review.save_session(s, p)
            self.assertTrue(os.path.isfile(p))
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
            self.assertIn("items", raw)
            s2 = review.load_session(p)
            self.assertEqual(s2.items[0].corrected_text, "world")
            self.assertEqual(s2.original_transcript, s.original_transcript)

    def test_no_audio_files_written(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            before = set(os.listdir(d))
            s = session_for("hello world", "hello word")
            review.apply_correction(s, s.items[0].id, "world")
            review.preview_corrected_text(s)
            review.recheck_reviewed(s, "en")
            review.save_session(s, os.path.join(d, "r.json"))
            names = set(os.listdir(d))
            self.assertEqual(names - before, {"r.json"})


@unittest.skipUnless(HAS_SOUNDFILE, "soundfile not installed")
class TestAudioBounds(unittest.TestCase):
    def _wav(self, d, name, seconds, sr=16000, silent=False):
        import soundfile as sf
        p = os.path.join(d, name)
        n = int(seconds * sr)
        data = (np.zeros(n) if silent
                else 0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / sr))
        sf.write(p, data.astype(np.float32), sr)
        return p

    def test_out_of_range_time_flagged(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self._wav(d, "a.wav", 5.0)
            s = session_for("hello world", "hello word", audio=p)
            s.items[0].start_time = 100.0
            s.items[0].end_time = 200.0
            issues = review.validate_item_audio(s, s.items[0].id)
            self.assertTrue(any("ขอบเขต" in x or "range" in x.lower() for x in issues))
            fixed = review.refresh_time_status(s)
            self.assertEqual(fixed.items[0].status, "ALIGNMENT_UNRELIABLE")

    def test_short_silent_segment_noted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self._wav(d, "s.wav", 1.0, silent=True)
            s = session_for("hello world", "hello word", audio=p)
            issues = review.validate_item_audio(s, s.items[0].id)
            self.assertTrue(any("เงียบ" in x or "silent" in x.lower() for x in issues))

    def test_wrong_audio_file_detected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p1 = self._wav(d, "a.wav", 2.0)
            p2 = self._wav(d, "b.wav", 2.0, silent=True)
            rep = analyze_transcript(TX("hello word"), p1, "hello world", "en")
            s = review.build_review(rep, p1)
            stale = review.check_stale(s, p2, "hello world")
            self.assertTrue(stale)

    def test_stale_on_changed_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self._wav(d, "a.wav", 2.0)
            s = session_for("hello world", "hello word", audio=p)
            self.assertFalse(review.check_stale(s, p, "hello world"))
            self.assertTrue(review.check_stale(s, p, "different ref"))


class TestNoReprocessing(unittest.TestCase):
    def test_review_module_has_no_audio_writing(self):
        import inspect
        import lyrics.review as R
        names = [n for n, _ in inspect.getmembers(R, inspect.isfunction)]
        for banned in ("reprocess", "retune", "pitch_shift", "rvc_infer",
                       "export_audio", "write_audio", "replace_result"):
            self.assertNotIn(banned, names)


if __name__ == "__main__":
    unittest.main()
