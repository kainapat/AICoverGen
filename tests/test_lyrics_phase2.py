"""Phase 2 tests: multilingual rules + timestamp granularity + fallback.

Pure unit tests (no model download). Real-ASR verification is done
separately with .venv CPU tiny on a real audio file (see final report).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyrics import TIMESTAMP_MODES, analyze_vocals, compare_texts
from lyrics.align import (
    SegmentInfo,
    WordSegment,
    attach_timestamps_with_granularity,
    build_segments_from_raw,
)
from lyrics.compare import (
    THAI_LIMITATION,
    UnsupportedLanguageError,
    compare_lyrics,
    get_language_rules,
    is_spaceless_language,
    normalize_text,
    register_language,
    tokenize_for_language,
)


class TestLanguageSelection(unittest.TestCase):
    def test_supported_th_en_auto(self):
        for lang in ("auto", "th", "en"):
            self.assertEqual(normalize_text("Hello สวัสดี", lang), normalize_text("Hello สวัสดี", lang))

    def test_unsupported_rejected(self):
        with self.assertRaises(UnsupportedLanguageError):
            normalize_text("hello", "xx")
        with self.assertRaises(UnsupportedLanguageError):
            compare_lyrics("a", "b", "xx")

    def test_register_extra_language(self):
        register_language("ja", "Japanese")
        self.assertEqual(normalize_text("こんにちは", "ja"), normalize_text("こんにちは", "ja"))
        # cleanup so other tests see original state
        from lyrics.compare import EXTRA_LANGUAGES, _LANGUAGE_RULES
        EXTRA_LANGUAGES.pop("ja", None)
        _LANGUAGE_RULES.pop("ja", None)

    def test_register_spaceless_flag(self):
        register_language("xx-ko", "TestKo", spaceless=True)
        try:
            self.assertTrue(is_spaceless_language("xx-ko"))
        finally:
            from lyrics.compare import EXTRA_LANGUAGES, _LANGUAGE_RULES
            EXTRA_LANGUAGES.pop("xx-ko", None)
            _LANGUAGE_RULES.pop("xx-ko", None)


class TestNormalization(unittest.TestCase):
    def test_th_normalizer_keeps_thai(self):
        out = normalize_text("เพลงรัก (Official MV)", "th")
        self.assertIn("เพลงรัก", out)
        self.assertNotIn("(", out)

    def test_en_case_punct_insensitive(self):
        self.assertEqual(normalize_text("Hello, WORLD!", "en"), "hello world")

    def test_thai_spaceless_flag_and_limitation(self):
        self.assertTrue(is_spaceless_language("th"))
        self.assertFalse(is_spaceless_language("en"))
        self.assertIn("ภาษาไทย", THAI_LIMITATION)

    def test_th_tokenize_chunks_long_spaceless(self):
        toks = tokenize_for_language("ก" * 200, "th")
        self.assertTrue(len(toks) > 1)
        self.assertTrue(all(len(t) <= 60 for t in toks))

    def test_get_rules_returns_dict(self):
        self.assertIsInstance(get_language_rules("th"), dict)


class TestTimestampGranularity(unittest.TestCase):
    def test_word_level_reliable(self):
        from lyrics.compare import Mismatch
        m = [Mismatch("substitution", "world", "word", 0, 1, 0, 1)]
        words = [WordSegment("word", 1.0, 1.5, 0.9)]
        ok, gran = attach_timestamps_with_granularity(m, words, [])
        self.assertTrue(ok)
        self.assertEqual(gran, "word")
        self.assertEqual((m[0].start_time, m[0].end_time), (1.0, 1.5))

    def test_missing_words_no_fake_times(self):
        from lyrics.compare import Mismatch
        m = [Mismatch("substitution", "world", "word", 0, 1, 0, 1)]
        ok, gran = attach_timestamps_with_granularity(m, [], [])
        self.assertFalse(ok)
        self.assertEqual(gran, "none")
        self.assertIsNone(m[0].start_time)
        self.assertIsNone(m[0].end_time)

    def test_segment_fallback_uses_real_times(self):
        from lyrics.compare import Mismatch
        m = [Mismatch("substitution", "hello", "hello", 0, 1, 0, 1)]
        segs = [SegmentInfo(text="hello world", start=10.0, end=12.0)]
        ok, gran = attach_timestamps_with_granularity(m, [], segs)
        self.assertEqual(gran, "segment")
        self.assertEqual((m[0].start_time, m[0].end_time), (10.0, 12.0))

    def test_segment_fallback_no_match_gives_none(self):
        from lyrics.compare import Mismatch
        m = [Mismatch("substitution", "zzz", "zzz", 0, 1, 0, 1)]
        segs = [SegmentInfo(text="hello world", start=1.0, end=2.0)]
        ok, gran = attach_timestamps_with_granularity(m, [], segs)
        self.assertEqual(gran, "none")
        self.assertIsNone(m[0].start_time)

    def test_no_uniform_division(self):
        # Even with many mismatches and segments, unmatched ones stay None.
        from lyrics.compare import Mismatch
        ms = [Mismatch("substitution", f"r{i}", f"h{i}", i, i + 1, i, i + 1) for i in range(5)]
        ok, gran = attach_timestamps_with_granularity(ms, [], [])
        for m in ms:
            self.assertIsNone(m.start_time)
        self.assertEqual(gran, "none")

    def test_build_segments_from_raw(self):
        segs = build_segments_from_raw([{"text": "hi", "start": 0.5, "end": 1.0}])
        self.assertEqual(len(segs), 1)
        self.assertEqual((segs[0].start, segs[0].end), (0.5, 1.0))

    def test_timestamp_modes_constant(self):
        self.assertEqual(set(TIMESTAMP_MODES), {"word", "segment", "none"})


class TestAnalyzeModes(unittest.TestCase):
    def test_invalid_timestamp_mode_falls_back(self):
        import lyrics as L
        orig = L.transcribe
        try:
            def fake_transcribe(*a, **k):
                from lyrics.asr import TranscriptionResult
                return TranscriptionResult(
                    text="hello word",
                    segments=[{"text": "hello word", "start": 0.0, "end": 2.0,
                               "words": [{"word": "hello", "start": 0.0, "end": 1.0, "probability": 0.9},
                                         {"word": "word", "start": 1.0, "end": 2.0, "probability": 0.9}]}],
                    language="en", language_probability=0.9)
            L.transcribe = fake_transcribe
            rep = analyze_vocals("dummy.wav", "hello world", "en", timestamp_mode="bogus")
            self.assertTrue(rep.ok)
            self.assertEqual(rep.timestamp_granularity, "word")
        finally:
            L.transcribe = orig

    def test_mode_none_gives_no_times(self):
        import lyrics as L
        orig = L.transcribe
        try:
            def fake_transcribe(*a, **k):
                from lyrics.asr import TranscriptionResult
                return TranscriptionResult(
                    text="hello word",
                    segments=[{"text": "hello word", "start": 0.0, "end": 2.0, "words": []}],
                    language="en", language_probability=0.8)
            L.transcribe = fake_transcribe
            rep = analyze_vocals("dummy.wav", "hello world", "en", timestamp_mode="none")
            self.assertEqual(rep.timestamp_granularity, "none")
        finally:
            L.transcribe = orig

    def test_asr_failure_never_raises(self):
        rep = analyze_vocals("/nonexistent/file.wav", "hello")
        self.assertFalse(rep.ok)
        self.assertIn("RVC", rep.error)

    def test_empty_and_invalid_inputs(self):
        with self.assertRaises(ValueError):
            compare_lyrics("   ", "  ")
        with self.assertRaises(ValueError):
            compare_lyrics(None, "hi")
        rep = compare_texts("hi", None)
        self.assertFalse(rep.ok)

    def test_mismatch_report_uses_suspicion_terms(self):
        rep = compare_texts("hello world", "hello word", "en")
        md = rep.to_markdown()
        self.assertIn("ความต่างที่น่าสงสัย", md)
        self.assertIn("เนื้อเพลงอ้างอิง", md)
        self.assertIn("ข้อความที่รู้จำได้", md)
        html = rep.to_html()
        self.assertIn("เนื้อเพลงอ้างอิง", html)
        self.assertIn("ข้อความที่รู้จำได้", html)

    def test_report_shows_selected_vs_detected(self):
        import lyrics as L
        orig = L.transcribe
        try:
            def fake_transcribe(*a, **k):
                from lyrics.asr import TranscriptionResult
                return TranscriptionResult(text="สวัสดี", segments=[], language="th",
                                           language_probability=0.7)
            L.transcribe = fake_transcribe
            rep = analyze_vocals("dummy.wav", "สวัสดี", "auto")
            md = rep.to_markdown()
            self.assertIn("ภาษาที่เลือก", md)
            self.assertIn("ภาษาที่ตรวจพบ", md)
        finally:
            L.transcribe = orig

    def test_cache_invalidation(self):
        rep = compare_texts("hello", "hello")
        self.assertTrue(rep.is_stale(reference="different"))
        self.assertFalse(rep.is_stale(reference="hello"))


if __name__ == "__main__":
    unittest.main()
