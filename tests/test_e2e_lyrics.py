"""Phase 5 end-to-end tests with REAL audio + REAL tiny ASR (.venv only).

Files (resolved at runtime, skipped when absent — never fabricated):
  song_output/0c1231cc669/song_0c1231cc669_Vocals_Main.wav   isolated lead vocal
  song_output/0c1231cc669/song_0c1231cc669_Vocals.wav        lead+backup mix
  song_output/0c1231cc669/song_0c1231cc669_Vocals_Backup.wav backup vocal
  downloads/*.mp3                                            full mix (if present)
No ground-truth lyrics exist: assertions are structural (types, hashes,
timelines, byte-preservation), never accuracy claims.
"""
import hashlib
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

try:
    from lyrics import postrvc
    from lyrics import review
    from lyrics import analyze_vocals, transcribe, unload_models
    from lyrics import eval as ev
    HAS_LYRICS = True
except Exception:
    HAS_LYRICS = False

SONG_DIR = Path("song_output") / "0c1231cc669"
VOC_MAIN = SONG_DIR / "song_0c1231cc669_Vocals_Main.wav"
VOC_MIX = SONG_DIR / "song_0c1231cc669_Vocals.wav"
VOC_BACKUP = SONG_DIR / "song_0c1231cc669_Vocals_Backup.wav"

NEEDS = HAS_SOUNDFILE and HAS_LYRICS and VOC_MAIN.is_file()


def excerpt(src: Path, seconds=30.0, start=30.0):
    import tempfile
    import soundfile as sfx
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    with sfx.SoundFile(str(src)) as f:
        sr = f.samplerate
        f.seek(int(start * sr))
        data = f.read(int(seconds * sr), dtype="float32", always_2d=True)
    sfx.write(tmp.name, data, sr)
    return tmp.name


@unittest.skipUnless(NEEDS, "needs .venv (soundfile+faster-whisper) + real vocal file")
class TestRealAudioE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ex_main = excerpt(VOC_MAIN)
        cls.ex_mix = excerpt(VOC_MIX) if VOC_MIX.is_file() else None
        cls.ex_backup = excerpt(VOC_BACKUP) if VOC_BACKUP.is_file() else None

    @classmethod
    def tearDownClass(cls):
        for p in (cls.ex_main, cls.ex_mix, cls.ex_backup):
            if p and os.path.isfile(p):
                os.remove(p)
        try:
            unload_models()
        except Exception:
            pass

    def test_thai_asr_returns_structured_result(self):
        tx = transcribe(self.ex_main, language="auto", model_size="tiny",
                        device="cpu", word_timestamps=True)
        print(f"\n[E2E] lang={tx.language} prob={tx.language_probability} "
              f"chars={len(tx.text)} segs={len(tx.segments)}")
        self.assertIsInstance(tx.text, str)
        self.assertIsInstance(tx.segments, list)
        for s in tx.segments:
            self.assertIn("words", s)

    def test_review_workflow_on_real_transcript(self):
        rep = analyze_vocals(self.ex_main, "", "auto", "tiny", "cpu",
                             timestamp_mode="word")
        self.assertTrue(rep.ok)
        sess = review.build_review(rep, self.ex_main)
        self.assertIn(sess.status, ("MATCH", "HAS_ITEMS", "NO_REFERENCE"))
        h0 = hashlib.blake2b(open(self.ex_main, "rb").read()).hexdigest()
        if sess.items:
            it = sess.items[0]
            if it.hyp_text:
                review.apply_correction(sess, it.id, it.hyp_text + "x")
                prev = review.preview_corrected_text(sess)
                self.assertIn(it.hyp_text + "x", prev)
                self.assertEqual(sess.original_transcript, rep.recognized_raw)
                review.confirm_correction(sess, it.id)
                review.revert_correction(sess, it.id)
                self.assertIsNone(sess.items[0].corrected_text)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            review.save_session(sess, p)
            s2 = review.load_session(p)
            self.assertEqual(s2.original_transcript, sess.original_transcript)
        h1 = hashlib.blake2b(open(self.ex_main, "rb").read()).hexdigest()
        self.assertEqual(h0, h1)

    def test_postrvc_cross_on_real_vocals(self):
        if not self.ex_backup:
            self.skipTest("no backup vocal file")
        out = postrvc.analyze_post_rvc(self.ex_main, self.ex_backup, "",
                                       "auto", "tiny", "cpu", "word")
        self.assertTrue(out.ok)
        self.assertIsNotNone(out.cross)
        self.assertEqual(out.cross.audio_hash, out.converted_audio_hash)
        self.assertIsInstance(out.sync_warning, bool)
        print(f"\n[E2E] cross_mism={out.cross.mismatch_count} "
              f"gran={out.cross.timestamp_granularity}")

    def test_mix_vs_main_bleed_pair(self):
        if not self.ex_mix:
            self.skipTest("no mixed vocal file")
        out = postrvc.analyze_post_rvc(self.ex_main, self.ex_mix, "",
                                       "auto", "tiny", "cpu", "word")
        self.assertTrue(out.ok)
        self.assertIsNotNone(out.cross)

    def test_metrics_on_real_files(self):
        info = postrvc.audio_info(str(VOC_MAIN))
        self.assertGreater(info["duration_sec"], 60.0)
        self.assertIn(info["sample_rate"], (40000, 41000, 44100, 48000))
        q = postrvc.signal_checks(str(VOC_MAIN))
        for key in ("peak", "rms", "clipping_ratio", "silent_ratio", "flags"):
            self.assertIn(key, q)
        print(f"\n[E2E] dur={info['duration_sec']:.1f}s sr={info['sample_rate']} "
              f"peak={q['peak']:.3f} rms={q['rms']:.4f} flags={q['flags']}")

    def test_invalid_format_is_error(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"not audio")
            p = f.name
        try:
            out = postrvc.analyze_post_rvc(p, self.ex_main, "", "en",
                                           "tiny", "cpu", "word")
            self.assertFalse(out.ok)
        finally:
            os.remove(p)

    def test_model_cache_reuse(self):
        from lyrics import asr as A
        m1 = A.get_model("tiny", "cpu")
        m2 = A.get_model("tiny", "cpu")
        self.assertIs(m1, m2)
        A.unload_models()
        self.assertEqual(dict(A._MODEL_CACHE), {})


@unittest.skipUnless(HAS_LYRICS, "lyrics package importable")
class TestFailureRecovery(unittest.TestCase):
    def test_asr_failure_keeps_pipeline_safe(self):
        rep = analyze_vocals("/nonexistent/file.wav", "hello")
        self.assertFalse(rep.ok)
        self.assertIn("RVC", rep.error or "")

    def test_review_revert_preserves_original(self):
        from lyrics import analyze_transcript
        from lyrics.asr import TranscriptionResult
        tx = TranscriptionResult(text="hello word", segments=[],
                                 language="en", language_probability=0.9)
        rep = analyze_transcript(tx, "dummy.wav", "hello world", "en")
        sess = review.build_review(rep, "dummy.wav")
        orig = sess.original_transcript
        if sess.items:
            review.apply_correction(sess, sess.items[0].id, "zzz")
            review.revert_correction(sess, sess.items[0].id)
        self.assertEqual(sess.original_transcript, orig)

    def test_wrong_file_timestamps_flagged(self):
        from lyrics import analyze_transcript
        from lyrics.asr import TranscriptionResult
        tx = TranscriptionResult(text="hello word", segments=[],
                                 language="en", language_probability=0.9)
        rep = analyze_transcript(tx, "dummy.wav", "hello world", "en")
        sess = review.build_review(rep, "dummy.wav")
        for it in sess.items:
            it.start_time, it.end_time = 9999.0, 9999.0
        review.refresh_time_status(sess)
        self.assertTrue(all(i.status == "ALIGNMENT_UNRELIABLE" or
                            not (i.hyp_text or "").strip() for i in sess.items))


if __name__ == "__main__":
    unittest.main()
