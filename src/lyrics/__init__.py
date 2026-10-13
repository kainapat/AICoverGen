"""Lyrics Intelligence — optional, fail-safe, disabled by default.

Public API:
  analyze_vocals(...)       transcribe vocals + compare against reference lyrics
  compare_texts(...)        pure comparison of two lyric strings (no ASR)
  compare_source_converted(...)  pure-text source/converted comparison utility.
    F.2 note: this helper is NOT wired into the RVC pipeline or WebUI; it is
    a tested utility for future/manual post-RVC analysis (Phase 3 scope).
Nothing here may break the RVC pipeline: ASR failures become error reports.
"""

from __future__ import annotations

from typing import List, Optional

from .align import (
    SegmentInfo,
    attach_timestamps,
    attach_timestamps_with_granularity,
    build_segments_from_raw,
    build_words_from_segments,
)
from .asr import (
    ASRError,
    DEFAULT_MODEL_SIZE,
    SUPPORTED_AUDIO_EXTS,
    SUPPORTED_MODEL_SIZES,
    AudioValidationError,
    ModelLoadError,
    TranscriptionResult,
    transcribe,
    unload_models,
    validate_audio,
)
from .compare import (
    AUTO_LANGUAGE,
    EXTRA_LANGUAGES,
    SUPPORTED_LANGUAGES,
    CompareResult,
    Mismatch,
    compare_lyrics,
    normalize_text,
    supported_languages,
)
from .report import LyricsReport, build_report, error_report

__all__ = [
    "analyze_vocals",
    "analyze_transcript",
    "compare_texts",
    "compare_source_converted",
    "compare_lyrics",
    "transcribe",
    "unload_models",
    "validate_audio",
    "build_report",
    "error_report",
    "LyricsReport",
    "TranscriptionResult",
    "CompareResult",
    "Mismatch",
    "SegmentInfo",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_MODEL_SIZES",
    "SUPPORTED_AUDIO_EXTS",
    "DEFAULT_MODEL_SIZE",
    "TIMESTAMP_MODES",
    "ASRError",
    "AudioValidationError",
    "ModelLoadError",
    "attach_timestamps",
    "attach_timestamps_with_granularity",
    "build_words_from_segments",
    "build_segments_from_raw",
]


def compare_texts(
    reference: str,
    recognized: str,
    language: str = "auto",
) -> LyricsReport:
    """Pure comparison without ASR (used by tests and post-RVC cross-check)."""
    try:
        result = compare_lyrics(reference, recognized, language)
    except Exception as e:
        return error_report(str(e))
    return build_report(reference, recognized, result, language=language)


TIMESTAMP_MODES = ("word", "segment", "none")


def analyze_transcript(
    tx: TranscriptionResult,
    audio_path: str = "",
    reference_lyrics: str = "",
    language: str = "auto",
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = "cpu",
    timestamp_mode: str = "word",
) -> LyricsReport:
    """Compare an existing transcription (no ASR inside). Never raises.

    Single source of truth shared by analyze_vocals() and Phase 3 post-RVC
    analysis so both sides of a comparison use identical logic.
    """
    warnings: List[str] = []
    if not (reference_lyrics or "").strip():
        warnings.append("ไม่มีเนื้อร้องอ้างอิง — แสดงเฉพาะผลถอดเสียง / No reference, showing transcription only")
        # F.6: norm_hyp means *normalized* text — derive it through the same
        # language-aware normalization; raw text stays in recognized_raw.
        try:
            norm_hyp = normalize_text(tx.text, language)
        except Exception:
            norm_hyp = tx.text
        result = CompareResult(norm_ref="", norm_hyp=norm_hyp, similarity=1.0)
        recognized = tx.text
    else:
        try:
            result = compare_lyrics(reference_lyrics, tx.text, language)
            recognized = tx.text
        except Exception as e:
            return error_report(str(e))
    mode = (timestamp_mode or "word").strip().lower()
    if mode not in TIMESTAMP_MODES:
        warnings.append(f"โหมดเวลา '{timestamp_mode}' ไม่รองรับ — ใช้ 'word' แทน")
        mode = "word"
    reliable = False
    granularity = "none"
    if mode != "none" and result.mismatches:
        try:
            words = build_words_from_segments(tx.segments) if mode == "word" else []
            segments = build_segments_from_raw(tx.segments)
            if mode == "segment":
                words = []
            reliable, granularity = attach_timestamps_with_granularity(
                result.mismatches, words, segments
            )
            if granularity == "segment":
                warnings.append(
                    "ใช้เวลาระดับช่วง (segment) — หยาบกว่าระดับคำ ให้ตรวจด้วยหู"
                )
            elif not reliable:
                warnings.append(
                    "ไม่มีเวลาที่เชื่อถือได้ (—) — ใช้เป็นแนวคร่าวๆ / Timestamps unreliable"
                )
        except Exception:
            warnings.append("แนบ timestamp ไม่สำเร็จ — แสดงผลแบบไม่มีเวลา")
            reliable, granularity = False, "none"
    if tx.language and language == AUTO_LANGUAGE:
        warnings.append(f"ตรวจภาษาอัตโนมัติได้: {tx.language} (อาจผิดสำหรับเพลงร้อง)")
    return build_report(
        reference_lyrics or "",
        recognized,
        result,
        language=language,
        detected_language=tx.language,
        language_probability=tx.language_probability,
        timestamp_reliable=reliable,
        timestamp_granularity=granularity,
        warnings=warnings,
        audio_path=audio_path,
        model_size=model_size,
        device=device,
    )


def analyze_vocals(
    audio_path: str,
    reference_lyrics: str = "",
    language: str = "auto",
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = "cpu",
    word_timestamps: bool = True,
    vad_filter: bool = False,
    timestamp_mode: str = "word",
) -> LyricsReport:
    """Transcribe vocals and compare with reference. Never raises on ASR failure."""
    warnings: List[str] = []
    try:
        tx = transcribe(
            audio_path,
            language=language,
            model_size=model_size,
            device=device,
            word_timestamps=word_timestamps,
            vad_filter=vad_filter,
        )
    except Exception as e:
        return error_report(
            f"Lyrics analysis failed but RVC pipeline is unaffected: {e}",
            warnings=[
                "การวิเคราะห์เนื้อร้องล้มเหลว — pipeline หลักยังทำงานต่อได้",
                "ASR ฟังเสียงร้องเพลงได้ไม่สมบูรณ์ ผลอาจคลาดเคลื่อน",
            ],
        )
    mode = timestamp_mode if word_timestamps else "none"
    rep = analyze_transcript(
        tx,
        audio_path=audio_path,
        reference_lyrics=reference_lyrics,
        language=language,
        model_size=model_size,
        device=device,
        timestamp_mode=mode,
    )
    if not word_timestamps:
        rep.warnings.insert(
            0, "ปิด word timestamps — รายงานนี้ไม่มีเวลาระดับคำ"
        )
    return rep


def compare_source_converted(
    source_text: str,
    converted_text: str,
    reference_lyrics: str = "",
    language: str = "auto",
) -> dict:
    """Post-RVC comparison utility: is converted vocal still recognizable?

    Pure-text function (no ASR inside) so results stay deterministic.
    NOT called by the RVC pipeline or WebUI — manual/future use only.
    Differences may come from voice timbre, singing style, bleed, or ASR
    errors — never auto-tune RVC settings from this output.
    """
    cross = compare_texts(source_text, converted_text, language)
    out = {"cross": cross}
    if (reference_lyrics or "").strip():
        out["source_vs_ref"] = compare_texts(reference_lyrics, source_text, language)
        out["converted_vs_ref"] = compare_texts(reference_lyrics, converted_text, language)
    return out
