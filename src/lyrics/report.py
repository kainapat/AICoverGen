"""Structured lyric-analysis results + readable bilingual reports."""

from __future__ import annotations

import hashlib
import html as _html
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .compare import CompareResult, Mismatch

# Max mismatches rendered in HTML; the rest collapse into a "+N more" note.
MAX_RENDERED_MISMATCHES = 50
# Long texts collapse behind <details> beyond this length.
COLLAPSE_AFTER = 240

_CATEGORY_COLOR = {
    "substitution": "#f1c21b",
    "omission": "#fa4d56",
    "insertion": "#42be65",
    "uncertain": "#8d8d8d",
}

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
    timestamp_granularity: str = "none"
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
        """True if this report no longer matches the given audio/reference.

        F.6 note: kept as public API for callers that cache reports.
        analyze_vocals() itself does NOT cache results — every call
        re-transcribes (only model weights are cached via get_model()).
        """
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
            "timestamp_granularity": self.timestamp_granularity,
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

    def _granularity_label(self) -> str:
        return {
            "word": "เวลาระดับคำ / word-level",
            "segment": "เวลาระดับช่วง / segment-level",
        }.get(self.timestamp_granularity, "ไม่มีเวลาที่เชื่อถือได้ (—)")

    def to_markdown(self) -> str:
        lines = ["## ผลตรวจเนื้อร้อง / Lyrics Check"]
        if self.error:
            lines.append(f"❌ **ผิดพลาด / Error:** {self.error}")
            lines.extend(f"- ⚠️ {w}" for w in self.warnings)
            return "\n".join(lines)
        if not self.mismatches:
            lines.append("✅ **ตรงกัน / Match** — ไม่พบคำที่ต่างอย่างมีนัยสำคัญ")
        else:
            shown = self.mismatches[:MAX_RENDERED_MISMATCHES]
            extra = len(self.mismatches) - len(shown)
            lines.append(
                f"🔍 **พบความต่างที่น่าสงสัย {self.mismatch_count} จุด** "
                f"(similarity {self.similarity:.2f}) / Possible differences below:"
            )
            for i, m in enumerate(shown, 1):
                if m.start_time is not None and m.end_time is not None:
                    t = f"{m.start_time:.1f}s–{m.end_time:.1f}s"
                else:
                    t = "—"
                ref = (m.ref_text[:200] + "…") if len(m.ref_text) > 200 else (m.ref_text or "—")
                hyp = (m.hyp_text[:200] + "…") if len(m.hyp_text) > 200 else (m.hyp_text or "—")
                lines.append(f"{i}. [{m.category}] `{t}` เนื้อเพลงอ้างอิง: {ref} → ข้อความที่รู้จำได้: {hyp}")
            if extra > 0:
                lines.append(f"…และอีก {extra} จุด / …and {extra} more")
            lines.append(f"⏱️ {self._granularity_label()}")
            if not self.timestamp_reliable:
                lines.append("⏱️ เวลาเป็นแนวคร่าวๆ ให้ตรวจด้วยหู — ใช้เป็นแนวคร่าวๆ เท่านั้น")
        if self.detected_language or self.language:
            prob = f" ({self.language_probability:.2f})" if self.language_probability else ""
            lines.append(f"\n🌐 ภาษาที่เลือก: {self.language or 'auto'} | ภาษาที่ตรวจพบ: {self.detected_language or '—'}{prob}")
        lines.extend(f"\n- ⚠️ {w}" for w in self.warnings)
        lines.append(f"\n> {DISCLAIMER_TH}")
        lines.append(f"> {DISCLAIMER_EN}")
        return "\n".join(lines)

    def to_html(self) -> str:
        """Readable card-style report for Gradio (wraps long Thai text, collapses)."""
        esc = _html.escape
        parts = [
            '<div style="border:1px solid var(--border-color-primary,#393939);border-radius:8px;'
            'padding:16px 18px;background:var(--block-background-fill,#161616);margin-top:8px;'
            'font-family:var(--font,system-ui,sans-serif);">',
            '<div style="font-size:1.05rem;font-weight:600;margin-bottom:10px;">'
            '🔍 ผลตรวจเนื้อร้อง / Lyrics Check</div>',
        ]
        if self.error:
            parts.append(f'<div style="color:#fa4d56;">❌ <b>ผิดพลาด / Error:</b> {esc(self.error)}</div>')
            for w in self.warnings:
                parts.append(f'<div style="color:#c6c6c6;">⚠️ {esc(w)}</div>')
            parts.append("</div>")
            return "".join(parts)
        if not self.mismatches:
            parts.append('<div style="color:#42be65;">✅ <b>ตรงกัน / Match</b> — ไม่พบคำที่ต่างอย่างมีนัยสำคัญ</div>')
        else:
            shown = self.mismatches[:MAX_RENDERED_MISMATCHES]
            extra = len(self.mismatches) - len(shown)
            pct = int(self.similarity * 100)
            parts.append(
                f'<div style="margin-bottom:10px;">🔍 พบจุดที่อาจต่าง '
                f"<b>{self.mismatch_count} จุด</b> "
                f'(similarity {self.similarity:.2f}) '
                f'<span style="display:inline-block;width:120px;height:8px;border-radius:4px;'
                f'background:rgba(255,255,255,.15);vertical-align:middle;">'
                f'<span style="display:inline-block;height:8px;width:{pct}%;border-radius:4px;'
                f'background:#0f62fe;"></span></span></div>'
            )
            for i, m in enumerate(shown, 1):
                color = _CATEGORY_COLOR.get(m.category, "#8d8d8d")
                if m.start_time is not None and m.end_time is not None:
                    t = f"{m.start_time:.1f}s – {m.end_time:.1f}s"
                else:
                    t = "ไม่มีเวลาที่เชื่อถือได้ (—)"
                parts.append(
                    '<div style="border:1px solid rgba(255,255,255,.12);border-radius:6px;'
                    'padding:10px 12px;margin-bottom:8px;">'
                    f'<div style="margin-bottom:6px;"><b>#{i}</b> '
                    f'<span style="display:inline-block;padding:1px 8px;border-radius:4px;font-size:.75rem;'
                    f'background:{color}22;border:1px solid {color};color:{color};">{esc(m.category)}</span> '
                    f'<span style="color:#c6c6c6;font-size:.8rem;">⏱️ {esc(t)}</span></div>'
                    f"{self._html_text_block('เนื้อเพลงอ้างอิง / Ref', m.ref_text)}"
                    f"{self._html_text_block('ข้อความที่รู้จำได้ / Heard', m.hyp_text)}"
                    "</div>"
                )
            if extra > 0:
                parts.append(f"<div>…และอีก {extra} จุด (…and {extra} more)</div>")
            parts.append(f"<div>⏱️ {esc(self._granularity_label())}</div>")
            if not self.timestamp_reliable:
                parts.append("<div>⏱️ เวลาเป็นแนวคร่าวๆ ให้ตรวจด้วยหู — ใช้เป็นแนวคร่าวๆ เท่านั้น</div>")
        if self.detected_language or self.language:
            prob = f" ({self.language_probability:.2f})" if self.language_probability else ""
            parts.append(
                f"<div>🌐 ภาษาที่เลือก: {esc(self.language or 'auto')} | "
                f"ภาษาที่ตรวจพบ: {esc(self.detected_language or '—')}{esc(prob)}</div>"
            )
        for w in self.warnings:
            parts.append(f'<div style="color:#c6c6c6;">⚠️ {esc(w)}</div>')
        parts.append(
            f'<div style="margin-top:10px;color:#8d8d8d;font-size:.8rem;">{esc(DISCLAIMER_TH)}<br>'
            f"{esc(DISCLAIMER_EN)}</div></div>"
        )
        return "".join(parts)

    @staticmethod
    def _html_text_block(label: str, text: str) -> str:
        esc = _html.escape
        body = text or "—"
        if len(body) > COLLAPSE_AFTER:
            head = esc(body[:COLLAPSE_AFTER]) + "…"
            return (
                f'<div style="margin:4px 0;"><span style="color:#8d8d8d;font-size:.78rem;">{esc(label)}:</span> '
                f'<div style="white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;">{head} '
                f"<details style=\"display:inline;\"><summary style=\"display:inline;cursor:pointer;"
                f"color:#4589ff;\">ดูทั้งหมด / more</summary>{esc(body)}</details></div></div>"
            )
        return (
            f'<div style="margin:4px 0;"><span style="color:#8d8d8d;font-size:.78rem;">{esc(label)}:</span> '
            f'<div style="white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;">{esc(body)}</div></div>'
        )


def build_report(
    reference_raw: str,
    recognized_raw: str,
    result: CompareResult,
    *,
    language: str = "auto",
    detected_language: str = "",
    language_probability: Optional[float] = None,
    timestamp_reliable: bool = False,
    timestamp_granularity: str = "none",
    warnings: Optional[List[str]] = None,
    audio_path: str = "",
    model_size: str = "",
    device: str = "",
) -> LyricsReport:
    gran = (timestamp_granularity or "none").strip().lower()
    if gran not in ("word", "segment", "none"):
        gran = "none"
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
        timestamp_granularity=gran,
        warnings=list(warnings or []),
        audio_hash=file_hash(audio_path) if audio_path and os.path.isfile(audio_path) else "",
        ref_hash=text_hash(reference_raw or ""),
        model_size=model_size,
        device=device,
    )


def error_report(message: str, *, warnings: Optional[List[str]] = None) -> LyricsReport:
    return LyricsReport(error=message, warnings=list(warnings or []))
