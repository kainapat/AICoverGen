"""Structured lyric-analysis results + readable bilingual reports."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .compare import CompareResult, Mismatch

DISCLAIMER_TH = (
    "หมายเหตุ: ASR ฟังเสียงร้องเพลงได้ไม่สมบูรณ์ ความต่างอาจมาจากเสียงร้อง "
    "เทคนิคการร้อง เสียงดนตรีปน หรือความผิดพลาดของ ASR เอง ไม่ได้แปลว่า RVC เปลี่ยนเนื้อร้องเสมอไป"
)
DISCLAIMER_EN = (
    "Note: singing ASR is imperfect. Differences may come from vocal style, "
    "instrumental bleed, or ASR errors — not necessarily changed lyrics from RVC."
)


def file_hash(path: str, n: int = 16) -> str:
    h = hashlib.blake2b()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()[:n]
    except OSError:
        return ""


def text_hash(text: str, n: int = 16) -> str:
    return hashlib.blake2b((text or "").encode("utf-8")).hexdigest()[:n]


@dataclass
class LyricsReport:
    reference_raw: str = ""
    recognized_raw: str = ""
    normalized_ref: str = ""
    normalized_hyp: str = ""
    language: str = "auto"
    detected_language: str = ""
    language_probability: Optional[float] = None
    mismatches: List[Mismatch] = field(default_factory=list)
    similarity: float = 1.0
    timestamp_reliable: bool = False
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    audio_hash: str = ""
    ref_hash: str = ""
    model_size: str = ""
    device: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)

    def is_stale(self, audio_path: str = "", reference: str = "") -> bool:
        """True if this report no longer matches the given audio/reference."""
        if audio_path and self.audio_hash != file_hash(audio_path):
            return True
        if reference is not None and self.ref_hash != text_hash(reference or ""):
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error": self.error,
            "language": self.language,
            "detected_language": self.detected_language,
            "language_probability": self.language_probability,
            "similarity": self.similarity,
            "timestamp_reliable": self.timestamp_reliable,
            "mismatch_count": self.mismatch_count,
            "mismatches": [
                {
                    "category": m.category,
                    "ref": m.ref_text,
                    "hyp": m.hyp_text,
                    "start": m.start_time,
                    "end": m.end_time,
                    "confidence": m.confidence,
                }
                for m in self.mismatches
            ],
            "warnings": list(self.warnings),
            "model_size": self.model_size,
            "device": self.device,
        }

    def to_markdown(self) -> str:
        lines = ["## ผลตรวจเนื้อร้อง / Lyrics Check"]
        if self.error:
            lines.append(f"❌ **ผิดพลาด / Error:** {self.error}")
            lines.extend(f"- ⚠️ {w}" for w in self.warnings)
            return "\n".join(lines)
        if not self.mismatches:
            lines.append("✅ **ตรงกัน / Match** — ไม่พบคำที่ต่างอย่างมีนัยสำคัญ")
        else:
            lines.append(
                f"🔍 **พบจุดที่อาจต่าง {self.mismatch_count} จุด** "
                f"(similarity {self.similarity:.2f}) / Possible differences below:"
            )
            lines.append("")
            lines.append("| # | ประเภท / Type | อ้างอิง / Ref | ฟังได้ / Heard | เวลา / Time |")
            lines.append("|---|---|---|---|---|")
            for i, m in enumerate(self.mismatches, 1):
                if m.start_time is not None and m.end_time is not None:
                    t = f"{m.start_time:.1f}s–{m.end_time:.1f}s"
                else:
                    t = "—" if not self.timestamp_reliable else "n/a"
                lines.append(
                    f"| {i} | {m.category} | {m.ref_text or '—'} | {m.hyp_text or '—'} | {t} |"
                )
            if not self.timestamp_reliable:
                lines.append("")
                lines.append("⏱️ เวลาระดับคำไม่น่าเชื่อถือ/ไม่มี — ใช้เป็นแนวคร่าวๆ เท่านั้น")
        if self.detected_language:
            prob = f" ({self.language_probability:.2f})" if self.language_probability else ""
            lines.append(f"\n🌐 ภาษาที่ตรวจได้ / Detected: {self.detected_language}{prob}")
        lines.extend(f"\n- ⚠️ {w}" for w in self.warnings)
        lines.append(f"\n> {DISCLAIMER_TH}")
        lines.append(f"> {DISCLAIMER_EN}")
        return "\n".join(lines)


def build_report(
    reference_raw: str,
    recognized_raw: str,
    result: CompareResult,
    *,
    language: str = "auto",
    detected_language: str = "",
    language_probability: Optional[float] = None,
    timestamp_reliable: bool = False,
    warnings: Optional[List[str]] = None,
    audio_path: str = "",
    model_size: str = "",
    device: str = "",
) -> LyricsReport:
    return LyricsReport(
        reference_raw=reference_raw or "",
        recognized_raw=recognized_raw or "",
        normalized_ref=result.norm_ref,
        normalized_hyp=result.norm_hyp,
        language=language,
        detected_language=detected_language,
        language_probability=language_probability,
        mismatches=list(result.mismatches),
        similarity=result.similarity,
        timestamp_reliable=timestamp_reliable,
        warnings=list(warnings or []),
        audio_hash=file_hash(audio_path) if audio_path and os.path.isfile(audio_path) else "",
        ref_hash=text_hash(reference_raw or ""),
        model_size=model_size,
        device=device,
    )


def error_report(message: str, *, warnings: Optional[List[str]] = None) -> LyricsReport:
    return LyricsReport(error=message, warnings=list(warnings or []))
