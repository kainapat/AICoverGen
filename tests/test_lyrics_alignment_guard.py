"""Regression tests for audit findings F.1 (index-space mapping) and F.3 (confidence).

F.1: hyp_start/hyp_end index into compare's hyp_tokens, but the old code used
them to slice ASR words directly. Different tokenizations must never yield
reliable word-level timestamps.
F.3: Mismatch.confidence must be ASR word probability (mean over the verified
span) or None — never the global similarity.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyrics.align import WordSegment, attach_timestamps_with_granularity
from lyrics.compare import Mismatch, compare_lyrics, normalize_text


def W(word, s, e, p=0.9):
    return WordSegment(word, s, e, p)


class TestIndexSpaceGuard(unittest.TestCase):
    def test_thai_count_mismatch_never_word(self):
        # hyp_tokens are 60-char chunks (3), ASR words are unrelated (8).
        ref = "ช่วยเดินไปบอกเขาเลยว่าฉันไม่ให้ไป" * 6
        hyp = "ช่วยเดินไปบอกเขาว่าฉันไม่ไป" * 6
        r = compare_lyrics(ref, hyp, "th")
        self.assertTrue(len(r.mismatches) > 0)
        words = [W("w%d" % i, float(i), float(i) + 0.9) for i in range(8)]
        ok, gran = attach_timestamps_with_granularity(r.mismatches, words, [])
        self.assertFalse(ok is True and gran == "word",
                         "unrelated index spaces must not report reliable word-level")

    def test_same_count_different_text_never_word(self):
        # Same counts (2 tokens vs 2 words) but different boundaries/content:
        # a len() check alone would wrongly pass this.
        m = [Mismatch("substitution", "ab", "ab", 0, 1, 0, 1)]
        m[0].hyp_text = "ab"
        words = [W("ax", 0.0, 1.0), W("by", 1.0, 2.0)]
        ok, gran = attach_timestamps_with_granularity(m, words, [])
        self.assertEqual(gran, "none")
        self.assertFalse(ok)
        self.assertIsNone(m[0].start_time)
        self.assertIsNone(m[0].end_time)

    def test_same_count_same_text_different_segmentation_keeps_word(self):
        # Same characters, different segmentation: mapping IS provable.
        m = [Mismatch("substitution", "ab cd", "ab cd", 0, 2, 0, 2)]
        m[0].hyp_text = "ab cd"
        words = [W("abc", 0.0, 0.5, 0.9), W("d", 0.5, 1.0, 0.7)]
        ok, gran = attach_timestamps_with_granularity(m, words, [])
        self.assertTrue(ok)
        self.assertEqual(gran, "word")
        self.assertEqual((m[0].start_time, m[0].end_time), (0.0, 1.0))

    def test_english_aligned_keeps_word(self):
        r = compare_lyrics("hello world", "hello word", "en")
        self.assertEqual(len(r.mismatches), 1)
        m = r.mismatches
        words = [W("hello", 0.0, 1.0, 0.9), W("word", 1.0, 2.0, 0.8)]
        ok, gran = attach_timestamps_with_granularity(m, words, [])
        self.assertTrue(ok)
        self.assertEqual(gran, "word")
        self.assertEqual((m[0].start_time, m[0].end_time), (1.0, 2.0))

    def test_punct_and_case_do_not_break_verified_mapping(self):
        # Whisper returns raw "Hello," while hyp tokens are normalized "hello".
        m = [Mismatch("substitution", "hello", "hello", 0, 1, 0, 1)]
        m[0].hyp_text = "hello"
        words = [W("Hello,", 0.0, 1.0)]
        ok, gran = attach_timestamps_with_granularity(m, words, [])
        self.assertTrue(ok)
        self.assertEqual(gran, "word")

    def test_unverifiable_falls_back_to_segment(self):
        from lyrics.align import SegmentInfo
        m = [Mismatch("substitution", "ab", "ab", 0, 1, 0, 1)]
        m[0].hyp_text = "ab"
        words = [W("ax", 0.0, 1.0)]
        segs = [SegmentInfo(text="xx ab yy", start=5.0, end=7.0)]
        ok, gran = attach_timestamps_with_granularity(m, words, segs)
        self.assertEqual(gran, "segment")
        self.assertEqual((m[0].start_time, m[0].end_time), (5.0, 7.0))

    def test_no_words_gives_none_not_fake(self):
        m = [Mismatch("substitution", "a", "b", 0, 1, 0, 1)]
        m[0].hyp_text = "b"
        ok, gran = attach_timestamps_with_granularity(m, [], [])
        self.assertEqual(gran, "none")
        self.assertIsNone(m[0].start_time)


class TestMismatchConfidence(unittest.TestCase):
    def test_compare_does_not_fake_confidence(self):
        r = compare_lyrics("hello world", "hello word", "en")
        for m in r.mismatches:
            self.assertIsNone(m.confidence)

    def test_word_span_confidence_is_mean_probability(self):
        m = [Mismatch("substitution", "hello", "hello", 0, 1, 0, 1)]
        m[0].hyp_text = "hello"
        words = [W("hello", 0.0, 1.0, 0.6)]
        attach_timestamps_with_granularity(m, words, [])
        self.assertAlmostEqual(m[0].confidence, 0.6)

    def test_confidence_none_without_probabilities(self):
        m = [Mismatch("substitution", "hello", "hello", 0, 1, 0, 1)]
        m[0].hyp_text = "hello"
        words = [WordSegment("hello", 0.0, 1.0, None)]
        ok, gran = attach_timestamps_with_granularity(m, words, [])
        self.assertEqual(gran, "word")
        self.assertIsNone(m[0].confidence)

    def test_confidence_never_leaks_across_mismatches(self):
        m = [Mismatch("substitution", "a b", "a b", 0, 2, 0, 2)]
        m[0].hyp_text = "a b"
        words = [W("a", 0.0, 1.0, 0.2), W("b", 1.0, 2.0, 0.8)]
        attach_timestamps_with_granularity(m, words, [])
        self.assertAlmostEqual(m[0].confidence, 0.5)


class TestEmptyRefNormalization(unittest.TestCase):
    def test_empty_ref_stores_normalized_hyp(self):
        import lyrics as L
        orig = L.transcribe
        try:
            def fake_transcribe(*a, **k):
                from lyrics.asr import TranscriptionResult
                return TranscriptionResult(text="Hello, WORLD!", segments=[],
                                           language="en", language_probability=0.9)
            L.transcribe = fake_transcribe
            rep = L.analyze_vocals("dummy.wav", "", "en")
            self.assertTrue(rep.ok)
            self.assertEqual(rep.normalized_hyp, normalize_text("Hello, WORLD!", "en"))
            self.assertEqual(rep.recognized_raw, "Hello, WORLD!")
        finally:
            L.transcribe = orig


if __name__ == "__main__":
    unittest.main()
