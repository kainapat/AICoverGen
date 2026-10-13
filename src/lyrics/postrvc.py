"""Phase 3 — Post-RVC vocal analysis (optional, read-only, fail-safe).

Compares the pre-RVC source vocal against the RVC-converted vocal using the
same ASR settings on both sides, plus optional reference lyrics. This module
only READS audio files and never touches RVC settings, never writes audio,
and never raises: failures become error reports so a finished cover is never
lost.

Timestamp rule: each side keeps times from its OWN file only. Cross
(source-vs-converted) mismatches are timestamped on the CONVERTED timeline
using the converted file's ASR words (with the F.1 mapping guard). Times are
never transferred across files and never synthesized.
"""

from __future__ import annotations

import html as _html
import os
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from .align import (
    attach_timestamps_with_granularity,
    build_segments_from_raw,
    build_words_from_segments,
)
from .asr import (
    DEFAULT_MODEL_SIZE,
    AudioValidationError,
    TranscriptionResult,
    transcribe,
    validate_audio,
)
from .compare import compare_lyrics, validate_language
from .report import LyricsReport, build_report, error_report, file_hash

SILENCE_RMS_THRESHOLD = 0.001  # ≈ -60 dBFS per 100 ms window
SILENCE_FLAG_RATIO = 0.5  # above this fraction of windows → "silent" flag
NEAR_SILENT_PEAK = 0.02
CLIPPING_LEVEL = 0.99
CLIPPING_FLAG_RATIO = 0.001
SYNC_ABS_TOL_SEC = 2.0
SYNC_REL_TOL = 0.05


def audio_info(audio_path: str) -> dict:
    """Validated audio metadata. Raises AudioValidationError on any problem."""
    path = validate_audio(audio_path)
    try:
        import soundfile as sf
    except ImportError as e:
        raise AudioValidationError(
            "soundfile is required for Post-RVC analysis."
        ) from e
    try:
        with sf.SoundFile(path) as f:
            frames = len(f)
            sr = f.samplerate
            channels = f.channels
    except Exception as e:
        raise AudioValidationError(f"Cannot read audio file: {e}") from e
    if frames <= 0 or sr <= 0:
        raise AudioValidationError("Audio file has no readable samples.")
    return {
        "path": path,
        "duration_sec": frames / float(sr),
        "sample_rate": sr,
        "channels": channels,
        "frames": frames,
    }


def signal_checks(audio_path: str) -> dict:
    """Low-risk vocal signal checks with documented meaning and limits.

    Returns {duration_sec, sample_rate, peak, clipping_ratio, silent_ratio,
    longest_silence: {start, end} | None, flags: [...]}.
    Flags are SUSPICIONS, not verdicts:
      silent      — >50% of 100ms windows below -60dBFS (may be intro/outro).
      near-silent — peak below 0.02 (very quiet render, or wrong file).
      clipping    — >0.1% samples at ±0.99 (hot master, not proof of damage).
    This module makes NO claim about naturalness, accent, or pronunciation.
    """
    info = audio_info(audio_path)
    import soundfile as sf

    with sf.SoundFile(info["path"]) as f:
        data = f.read(dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    sr = info["sample_rate"]
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    # RMS overall level (linear, full-scale ref): loudness-adjacent metric,
    # NOT a quality verdict. See eval.format_metrics_block for the disclaimer.
    rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
    clipping_ratio = float(np.mean(np.abs(mono) >= CLIPPING_LEVEL)) if mono.size else 0.0
    win = max(int(sr * 0.1), 1)
    n_win = max(len(mono) // win, 1)
    silent_windows = 0
    longest = {"start": 0.0, "end": 0.0, "length": 0.0}
    run_start: Optional[int] = None
    for i in range(n_win):
        chunk = mono[i * win:(i + 1) * win]
        # NOTE: must not reuse the name `rms` here — it holds the overall
        # level computed above (F-bug caught by Phase 5 real-audio check).
        w_rms = float(np.sqrt(np.mean(chunk ** 2))) if chunk.size else 0.0
        if w_rms < SILENCE_RMS_THRESHOLD:
            silent_windows += 1
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                length = (i - run_start) * win / sr
                if length > longest["length"]:
                    longest = {"start": run_start * win / sr,
                               "end": i * win / sr, "length": length}
                run_start = None
    if run_start is not None:
        length = (n_win - run_start) * win / sr
        if length > longest["length"]:
            longest = {"start": run_start * win / sr,
                       "end": n_win * win / sr, "length": length}
    silent_ratio = silent_windows / n_win
    flags: List[str] = []
    if silent_ratio > SILENCE_FLAG_RATIO:
        flags.append("silent: เกินครึ่งของไฟล์เงียบกว่า -60dBFS (อาจเป็นช่วงนำ/ท้ายเพลง)")
    elif peak < NEAR_SILENT_PEAK and mono.size:
        flags.append("near-silent: สัญญาณเบามาก อาจเรนเดอร์ผิดหรือผิดไฟล์")
    if clipping_ratio > CLIPPING_FLAG_RATIO:
        flags.append("clipping: สัญญาณแตะ ±0.99 (มาสเตอร์ดัง ไม่ใช่หลักฐานว่าเสียงเสีย)")
    return {
        "duration_sec": info["duration_sec"],
        "sample_rate": sr,
        "peak": peak,
        "rms": rms,
        "clipping_ratio": clipping_ratio,
        "silent_ratio": silent_ratio,
        "longest_silence": (
            {"start": longest["start"], "end": longest["end"]}
            if longest["length"] > 0 else None
        ),
        "flags": flags,
    }


def clamp_segment(start: Optional[float], end: Optional[float], duration: float) -> dict:
    """Clamp a reported time span into [0, duration] for safe re-listening.

    No audio is cut here; this only validates boundaries. `clamped` is True
    whenever the input was adjusted (including None inputs).
    """
    s = 0.0 if start is None else float(start)
    e = float(duration) if end is None else float(end)
    clamped = False
    if s != (0.0 if start is None else float(start)) or start is None or end is None:
        clamped = True
    if s < 0.0:
        s = 0.0
        clamped = True
    if e > duration:
        e = float(duration)
        clamped = True
    if e < s:
        e = s
        clamped = True
    return {"start": s, "end": e, "clamped": clamped}


@dataclass
class PostRVCReport:
    source_path: str = ""
    converted_path: str = ""
    source_transcript: str = ""
    converted_transcript: str = ""
    source_audio_hash: str = ""
    converted_audio_hash: str = ""
    source_vs_ref: Optional[LyricsReport] = None
    converted_vs_ref: Optional[LyricsReport] = None
    cross: Optional[LyricsReport] = None
    source_quality: dict = field(default_factory=dict)
    converted_quality: dict = field(default_factory=dict)
    src_duration: float = 0.0
    conv_duration: float = 0.0
    sync_warning: bool = False
    language: str = "auto"
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    model_size: str = ""
    device: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None

    def _case_block(self, title: str, rep: Optional[LyricsReport]) -> List[str]:
        lines = [f"### {title}"]
        if rep is None:
            lines.append("— (ไม่มีข้อมูล / skipped: ไม่มีเนื้อเพลงอ้างอิง)")
            return lines
        if not rep.ok:
            lines.append(f"❌ {rep.error}")
            return lines
        if not rep.mismatches:
            lines.append("✅ ตรงกัน / Match")
        else:
            lines.append(
                f"🔍 ความต่างที่น่าสงสัย {rep.mismatch_count} จุด "
                f"(similarity {rep.similarity:.2f}, สูตร SequenceMatcher ratio — "
                f"ดูแยกเป็นเคส ไม่ใช่คะแนนรวม)"
            )
            for i, m in enumerate(rep.mismatches[:20], 1):
                t = (f"{m.start_time:.1f}s–{m.end_time:.1f}s"
                     if m.start_time is not None and m.end_time is not None else "—")
                lines.append(f"{i}. [{m.category}] `{t}` {m.ref_text or '—'} → {m.hyp_text or '—'}")
            if rep.mismatch_count > 20:
                lines.append(f"…และอีก {rep.mismatch_count - 20} จุด")
        return lines

    def to_markdown(self) -> str:
        lines = ["## ผลตรวจหลัง RVC / Post-RVC Analysis"]
        if self.error:
            lines.append(f"❌ **ผิดพลาด / Error:** {self.error}")
            lines.extend(f"- ⚠️ {w}" for w in self.warnings)
            return "\n".join(lines)
        lines.append(
            f"⏱️ ต้นฉบับ {self.src_duration:.1f}s | หลัง RVC {self.conv_duration:.1f}s"
            + (" ⚠️ **ความยาวต่างกันมาก — เวลาของแต่ละฝั่งอ้างอิงไฟล์ของตัวเองเท่านั้น**"
               if self.sync_warning else "")
        )
        lines.extend(self._case_block("เคส 1 — เนื้อเพลงอ้างอิง vs Transcript ต้นฉบับ", self.source_vs_ref))
        lines.extend(self._case_block("เคส 2 — เนื้อเพลงอ้างอิง vs Transcript หลัง RVC", self.converted_vs_ref))
        lines.extend(self._case_block("เคส 3 — Transcript ต้นฉบับ vs Transcript หลัง RVC", self.cross))
        if self.cross is not None and self.cross.ok:
            lines.append(
                f"⏱️ เวลาของเคส 3 อ้างอิงไฟล์เสียง**หลัง RVC** ({self.cross.timestamp_granularity})")
        lines.append("### เคส 4 — คุณภาพสัญญาณเสียง (สัญญาณให้ตรวจสอบ ไม่ใช่คำตัดสิน)")
        for label, q in (("ต้นฉบับ", self.source_quality), ("หลัง RVC", self.converted_quality)):
            if not q:
                lines.append(f"- {label}: —")
                continue
            flag_txt = "; ".join(q.get("flags", [])) or "ปกติ / no flags"
            lines.append(
                f"- {label}: peak {q.get('peak', 0):.3f}, rms {q.get('rms', 0):.4f}, "
                f"เงียบ {q.get('silent_ratio', 0):.0%}, "
                f"clip {q.get('clipping_ratio', 0):.2%} → {flag_txt}")
        lines.append("### เคส 5 — ข้อจำกัด")
        lines.append(
            "- ความต่างทุกจุดคือ**ข้อสงสัยให้ฟังด้วยหู** ไม่ใช่หลักฐานว่า RVC ทำเนื้อเพลงผิด/เพี้ยน")
        lines.append(
            "- ASR ฟังเสียงร้องเพลงได้ไม่สมบูรณ์ และผลอาจต่างกันเล็กน้อยระหว่างรอบ "
            "(temperature fallback)")
        if self.source_vs_ref is None:
            lines.append(
                "- ไม่ได้ให้เนื้อเพลงอ้างอิง: เคส 3 เป็นการ**เปรียบเทียบ Transcript** "
                "ไม่ใช่การยืนยันว่าเนื้อเพลงถูกต้อง")
        lines.extend(f"- ⚠️ {w}" for w in self.warnings)
        return "\n".join(lines)

    def to_html(self) -> str:
        esc = _html.escape
        parts = [
            '<div style="border:1px solid var(--border-color-primary,#393939);border-radius:8px;'
            'padding:16px 18px;background:var(--block-background-fill,#161616);margin-top:8px;">',
            '<div style="font-size:1.05rem;font-weight:600;margin-bottom:10px;">'
            '🔍 ผลตรวจหลัง RVC / Post-RVC Analysis</div>',
        ]
        if self.error:
            parts.append(f'<div style="color:#fa4d56;">❌ <b>ผิดพลาด / Error:</b> {esc(self.error)}</div>')
            for w in self.warnings:
                parts.append(f'<div>⚠️ {esc(w)}</div>')
            parts.append("</div>")
            return "".join(parts)
        sync = (" ⚠️ <b>ความยาวต่างกันมาก — เวลาของแต่ละฝั่งอ้างอิงไฟล์ของตัวเองเท่านั้น</b>"
                if self.sync_warning else "")
        parts.append(
            f"<div>⏱️ ต้นฉบับ {self.src_duration:.1f}s | หลัง RVC {self.conv_duration:.1f}s{sync}</div>")
        for title, rep in (
            ("เคส 1 — อ้างอิง vs ต้นฉบับ", self.source_vs_ref),
            ("เคส 2 — อ้างอิง vs หลัง RVC", self.converted_vs_ref),
            ("เคส 3 — Transcript ต้นฉบับ vs หลัง RVC", self.cross),
        ):
            parts.append(f"<div style='margin-top:8px;font-weight:600;'>{esc(title)}</div>")
            if rep is None:
                parts.append("<div>— (ไม่มีเนื้อเพลงอ้างอิง)</div>")
            elif not rep.ok:
                parts.append(f"<div>❌ {esc(rep.error or '')}</div>")
            elif not rep.mismatches:
                parts.append('<div style="color:#42be65;">✅ ตรงกัน / Match</div>')
            else:
                parts.append(
                    f"<div>🔍 ความต่างที่น่าสงสัย <b>{rep.mismatch_count}</b> จุด "
                    f"(similarity {rep.similarity:.2f})</div>")
        parts.append(
            "<div style='margin-top:8px;color:#8d8d8d;font-size:.8rem;'>"
            "ความต่างทุกจุดคือข้อสงสัยให้ฟังด้วยหู ไม่ใช่หลักฐานว่า RVC ทำผิด; "
            "ASR อาจให้ผลต่างกันเล็กน้อยระหว่างรอบ</div></div>")
        return "".join(parts)


def _tx_or_report(label: str, path: str, **tx_kwargs) -> tuple:
    """Transcribe one side; returns (TranscriptionResult | None, error_text | None)."""
    try:
        return transcribe(path, **tx_kwargs), None
    except Exception as e:
        return None, f"{label} ({path}): {e}"


def analyze_post_rvc(
    source_path: str,
    converted_path: str,
    reference_lyrics: str = "",
    language: str = "auto",
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = "cpu",
    timestamp_mode: str = "word",
    vad_filter: bool = False,
) -> PostRVCReport:
    """Compare pre-RVC source vocal vs RVC-converted vocal. Never raises.

    Both sides are transcribed with IDENTICAL settings so the transcripts are
    comparable. Read-only: no audio is written, no RVC setting exists in this
    signature (verified by tests), and a finished cover is never deleted.
    """
    # NOTE: signature intentionally has no RVC parameters (pitch, index_rate,
    # filter_radius, rms_mix_rate, protect, f0_method) — analysis must never
    # retune conversion. Covered by test_no_rvc_settings_in_signature.
    warnings: List[str] = []
    try:
        src_info = audio_info(source_path)
        conv_info = audio_info(converted_path)
    except Exception as e:
        return PostRVCReport(
            source_path=source_path or "", converted_path=converted_path or "",
            error=f"Post-RVC analysis failed: {e}", warnings=warnings,
            language=language, model_size=model_size, device=device)
    try:
        validate_language(language)
    except Exception as e:
        return PostRVCReport(
            source_path=src_info["path"], converted_path=conv_info["path"],
            error=f"Post-RVC analysis failed: {e}", warnings=warnings,
            language=language, model_size=model_size, device=device)

    tx_kwargs = dict(language=language, model_size=model_size, device=device,
                      word_timestamps=(timestamp_mode != "none"),
                      vad_filter=vad_filter)
    tx_src, err_src = _tx_or_report("source", src_info["path"], **tx_kwargs)
    tx_conv, err_conv = _tx_or_report("converted", conv_info["path"], **tx_kwargs)
    if err_src or err_conv:
        failed = "; ".join(x for x in (err_src, err_conv) if x)
        return PostRVCReport(
            source_path=src_info["path"], converted_path=conv_info["path"],
            error=f"Post-RVC analysis failed on {'source' if err_src else ''}"
                  f"{' + ' if err_src and err_conv else ''}"
                  f"{'converted' if err_conv else ''} audio: {failed}",
            warnings=warnings + [
                "การวิเคราะห์ล้มเหลว — ไฟล์ cover ที่สร้างสำเร็จแล้วไม่ได้รับผลกระทบ",
            ],
            language=language, model_size=model_size, device=device)

    src_empty = not (tx_src.text or "").strip()
    conv_empty = not (tx_conv.text or "").strip()
    if src_empty:
        warnings.append("ASR ฟังเสียงต้นฉบับได้ว่างเปล่า — อาจเป็นท่อนดนตรี/เงียบ หรือร้องไม่ชัด")
    if conv_empty:
        warnings.append("ASR ฟังเสียงหลัง RVC ได้ว่างเปล่า — ให้ฟังช่วงนั้นด้วยหู (อาจเป็น artifact หรือท่อนเงียบ)")
    if src_empty and conv_empty:
        return PostRVCReport(
            source_path=src_info["path"], converted_path=conv_info["path"],
            source_transcript="", converted_transcript="",
            source_audio_hash=file_hash(src_info["path"]),
            converted_audio_hash=file_hash(conv_info["path"]),
            src_duration=src_info["duration_sec"], conv_duration=conv_info["duration_sec"],
            error="ASR ฟังเสียงไม่ได้ทั้งสองฝั่ง (empty transcripts) — ไม่มีอะไรให้เปรียบเทียบ",
            warnings=warnings, language=language,
            model_size=model_size, device=device)

    # Imported here to avoid a hard dependency cycle at module load.
    from . import analyze_transcript as _analyze_transcript

    has_ref = bool((reference_lyrics or "").strip())
    if has_ref:
        src_vs_ref = _analyze_transcript(tx_src, src_info["path"], reference_lyrics,
                                         language, model_size, device, timestamp_mode)
        conv_vs_ref = _analyze_transcript(tx_conv, conv_info["path"], reference_lyrics,
                                          language, model_size, device, timestamp_mode)
    else:
        src_vs_ref = None
        conv_vs_ref = None
        warnings.append(
            "ไม่ได้ให้เนื้อเพลงอ้างอิง — เคส 3 เป็นการเปรียบเทียบ Transcript "
            "ระหว่างสองไฟล์ ไม่ใช่การยืนยันว่าเนื้อเพลงถูกต้อง")

    # Cross: source transcript vs converted transcript, timestamped on the
    # CONVERTED timeline (hyp side) with the F.1 mapping guard.
    try:
        cross_result = compare_lyrics(tx_src.text, tx_conv.text, language)
    except Exception as e:
        return PostRVCReport(
            source_path=src_info["path"], converted_path=conv_info["path"],
            source_transcript=tx_src.text, converted_transcript=tx_conv.text,
            source_audio_hash=file_hash(src_info["path"]),
            converted_audio_hash=file_hash(conv_info["path"]),
            source_vs_ref=src_vs_ref, converted_vs_ref=conv_vs_ref,
            src_duration=src_info["duration_sec"], conv_duration=conv_info["duration_sec"],
            error=f"เปรียบเทียบ Transcript ไม่ได้: {e}",
            warnings=warnings, language=language,
            model_size=model_size, device=device)
    if timestamp_mode == "none" or not cross_result.mismatches:
        cross = build_report(tx_src.text, tx_conv.text, cross_result,
                             language=language,
                             detected_language=tx_conv.language,
                             language_probability=tx_conv.language_probability,
                             timestamp_reliable=False, timestamp_granularity="none",
                             warnings=[],
                             audio_path=conv_info["path"],
                             model_size=model_size, device=device)
    else:
        conv_words = (build_words_from_segments(tx_conv.segments)
                      if timestamp_mode == "word" else [])
        conv_segments = build_segments_from_raw(tx_conv.segments)
        reliable, gran = attach_timestamps_with_granularity(
            cross_result.mismatches, conv_words, conv_segments)
        if gran == "segment":
            warnings.append("เคส 3 ใช้เวลาระดับช่วง — หยาบกว่าระดับคำ ให้ตรวจด้วยหู")
        elif not reliable:
            warnings.append("เคส 3 ไม่มีเวลาที่เชื่อถือได้ (—)")
        cross = build_report(tx_src.text, tx_conv.text, cross_result,
                             language=language,
                             detected_language=tx_conv.language,
                             language_probability=tx_conv.language_probability,
                             timestamp_reliable=reliable, timestamp_granularity=gran,
                             warnings=[],
                             audio_path=conv_info["path"],
                             model_size=model_size, device=device)

    try:
        src_q = signal_checks(src_info["path"])
    except Exception:
        src_q = {}
    try:
        conv_q = signal_checks(conv_info["path"])
    except Exception:
        conv_q = {}

    dur_diff = abs(src_info["duration_sec"] - conv_info["duration_sec"])
    sync_warning = dur_diff > max(SYNC_ABS_TOL_SEC,
                                  SYNC_REL_TOL * src_info["duration_sec"])
    if sync_warning:
        warnings.append(
            f"ความยาวเสียงต่างกัน {dur_diff:.1f}s — เวลาของแต่ละฝั่งอ้างอิงไฟล์ของตัวเองเท่านั้น "
            f"ห้ามนำเวลาข้ามไฟล์โดยไม่ตรวจ offset")

    return PostRVCReport(
        source_path=src_info["path"], converted_path=conv_info["path"],
        source_transcript=tx_src.text, converted_transcript=tx_conv.text,
        source_audio_hash=file_hash(src_info["path"]),
        converted_audio_hash=file_hash(conv_info["path"]),
        source_vs_ref=src_vs_ref, converted_vs_ref=conv_vs_ref, cross=cross,
        source_quality=src_q, converted_quality=conv_q,
        src_duration=src_info["duration_sec"], conv_duration=conv_info["duration_sec"],
        sync_warning=sync_warning, language=language, warnings=warnings,
        model_size=model_size, device=device)
