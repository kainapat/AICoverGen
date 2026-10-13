import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyrics import compare_source_converted, compare_texts
from lyrics.align import WordSegment, attach_timestamps
from lyrics.asr import AudioValidationError, transcribe
from lyrics.compare import (
    Mismatch,
    UnsupportedLanguageError,
    chunk_long_tokens,
    compare_lyrics,
    normalize_text,
)
from lyrics.report import LyricsReport


class TestNormalize(unittest.TestCase):
    def test_punctuation_and_whitespace_ignored(self):
        a = normalize_text("Hello,  World!  สวัสดี...ครับ", "en")
        b = normalize_text("hello world สวัสดีครับ", "en")
        self.assertEqual(a, b)

    def test_thai_text(self):
        self.assertEqual(
            normalize_text("เพลงรัก (Official MV)", "th"), "เพลงรัก official mv"
        )

    def test_invalid_language(self):
        with self.assertRaises(UnsupportedLanguageError):
            normalize_text("hello", "xx")

    def test_non_string(self):
        with self.assertRaises(ValueError):
            normalize_text(None)


class TestCompare(unittest.TestCase):
    def test_identical(self):
        r = compare_lyrics("hello world", "hello world!")
        self.assertEqual(r.similarity, 1.0)
        self.assertEqual(r.mismatches, [])

    def test_substitution(self):
        r = compare_lyrics("hello world", "hello word")
        self.assertEqual(len(r.mismatches), 1)
        self.assertEqual(r.mismatches[0].category, "substitution")

    def test_omission(self):
        r = compare_lyrics("a b c d", "a b d")
        cats = [m.category for m in r.mismatches]
        self.assertIn("omission", cats)

    def test_insertion(self):
        r = compare_lyrics("a b d", "a b c d")
        cats = [m.category for m in r.mismatches]
        self.assertIn("insertion", cats)

    def test_thai_compare(self):
        r = compare_lyrics("ฉันรักเธอ", "ฉันรักเธอ", "th")
        self.assertEqual(r.mismatches, [])

    def test_empty_both_raises(self):
        with self.assertRaises(ValueError):
            compare_lyrics("   ", "  ")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            compare_lyrics(None, "hi")


class TestAlign(unittest.TestCase):
    def test_missing_timestamps_unreliable(self):
        m = [Mismatch("substitution", "world", "word", 1, 2, 1, 2)]
        self.assertFalse(attach_timestamps(m, []))
        self.assertIsNone(m[0].start_time)

    def test_partial_times_unreliable(self):
        m = [Mismatch("substitution", "world", "word", 0, 1, 0, 1)]
        words = [WordSegment("word", None, None)]
        self.assertFalse(attach_timestamps(m, words))

    def test_valid_times_reliable(self):
        m = [Mismatch("substitution", "world", "word", 0, 1, 0, 1)]
        words = [WordSegment("word", 1.0, 1.5, 0.9)]
        self.assertTrue(attach_timestamps(m, words))
        self.assertEqual((m[0].start_time, m[0].end_time), (1.0, 1.5))


class TestReportAndCache(unittest.TestCase):
    def test_error_report_never_raises_pipeline(self):
        rep = compare_texts("hi", None)
        self.assertFalse(rep.ok)
        self.assertIn("Error", rep.to_markdown())

    def test_stale_on_audio_change(self, tmp_path=None):
        import tempfile, os

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(b"abc")
            p = f.name
        try:
            rep = compare_texts("hello", "hello")
            rep.audio_hash = "x"
            self.assertTrue(rep.is_stale(audio_path=p, reference="hello"))
        finally:
            os.remove(p)

    def test_stale_on_ref_change(self):
        rep = compare_texts("hello", "hello")
        self.assertTrue(rep.is_stale(reference="different"))
        self.assertFalse(rep.is_stale(reference="hello"))

    def test_asr_failure_returns_error_report(self):
        # analyze_vocals must not raise; missing file -> error report
        from lyrics import analyze_vocals

        rep = analyze_vocals("/nonexistent/file.wav", "hello")
        self.assertFalse(rep.ok)
        self.assertIn("RVC", rep.error)

    def test_unsupported_audio_format(self):
        with self.assertRaises(AudioValidationError):
            transcribe("song.txt")


class TestPostRVC(unittest.TestCase):
    def test_cross_compare(self):
        out = compare_source_converted("hello world", "hello word", "hello world")
        self.assertIn("cross", out)
        self.assertIn("source_vs_ref", out)
        self.assertEqual(out["source_vs_ref"].mismatch_count, 0)
        self.assertEqual(out["converted_vs_ref"].mismatch_count, 1)


class TestChunking(unittest.TestCase):
    def test_long_thai_token_splits(self):
        chunks = chunk_long_tokens(["ก" * 200])
        self.assertTrue(len(chunks) > 1)
        self.assertTrue(all(len(c) <= 60 for c in chunks))

    def test_short_tokens_untouched(self):
        self.assertEqual(chunk_long_tokens(["hello", "world"]), ["hello", "world"])

    def test_whole_song_not_one_giant_mismatch(self):
        ref = "ช่วยเดินไปบอกเขาเลยว่าฉันไม่ให้ไป" * 10  # spaceless Thai
        hyp = "ช่วยเดินไปบอกเขาว่าฉันไม่ไป" * 10
        r = compare_lyrics(ref, hyp, "th")
        self.assertTrue(len(r.mismatches) > 1)
        for m in r.mismatches:
            self.assertLessEqual(len(m.ref_text), 400)
            self.assertLessEqual(len(m.hyp_text), 400)


class TestHtmlReport(unittest.TestCase):
    def test_html_escapes_and_wraps(self):
        rep = compare_texts("สวัสดี <b>โลก</b>", "สวัสดีชาวโลก")
        out = rep.to_html()
        self.assertNotIn("<b>โลก</b>", out)
        self.assertIn("break-word", out)
        self.assertIn("substitution", out)

    def test_html_collapses_long_text(self):
        rep = compare_texts("ก" * 500, "ข" * 500, "th")
        out = rep.to_html()
        self.assertIn("<details", out)

    def test_html_caps_mismatch_count(self):
        from lyrics.report import LyricsReport

        rep = LyricsReport(
            mismatches=[Mismatch("substitution", "a", "b")] * 120,
            similarity=0.01,
        )
        out = rep.to_html()
        self.assertIn("120", out)
        self.assertIn("more", out)

    def test_html_error_path(self):
        rep = compare_texts("hi", None)
        out = rep.to_html()
        self.assertIn("Error", out)


if __name__ == "__main__":
    unittest.main()
