"""Phase 4 — lyric error review & user correction workflow (optional).

Read-only w.r.t. audio: this module never writes/cuts audio files and never
retunes RVC. The Original ASR Transcript is immutable; user edits live in
per-item `corrected_text` plus an audit-trail `history`. Nothing is applied
silently — every mutation needs an explicit call with an actor name.

Review statuses (item level unless noted):
  MATCH                 — span identical (session level: nothing to review).
  POSSIBLE_MISMATCH     — substitution / uncertain diff.
  MISSING_TEXT          — reference text not found in ASR (omission).
  EXTRA_TEXT            — ASR text with no reference counterpart (insertion).
  ALIGNMENT_UNRELIABLE  — item needs time but none is trustworthy.
  ASR_FAILED            — session level: analysis itself failed.
  NO_REFERENCE          — session level: nothing to review against.
Statuses describe EVIDENCE, never the cause: a mismatch is not proof RVC
changed the lyrics.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .compare import compare_lyrics
from .report import LyricsReport, file_hash, text_hash

REVIEW_STATUSES = (
    "MATCH",
    "POSSIBLE_MISMATCH",
    "MISSING_TEXT",
    "EXTRA_TEXT",
    "ALIGNMENT_UNRELIABLE",
    "ASR_FAILED",
    "NO_REFERENCE",
)

SESSION_STATUSES = ("MATCH", "HAS_ITEMS", "ASR_FAILED", "NO_REFERENCE")

_KIND_TO_STATUS = {
    "substitution": "POSSIBLE_MISMATCH",
    "uncertain": "POSSIBLE_MISMATCH",
    "omission": "MISSING_TEXT",
    "insertion": "EXTRA_TEXT",
}

REVIEW_VERSION = 1


@dataclass
class ReviewItem:
    id: str = ""
    kind: str = ""
    status: str = "POSSIBLE_MISMATCH"
    ref_text: str = ""
    hyp_text: str = ""
    corrected_text: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    time_reliable: bool = False
    confidence: Optional[float] = None
    confidence_source: str = "none"
    reason: str = ""
    reviewed: bool = False
    confirmed: bool = False
    history: List[Dict] = field(default_factory=list)


@dataclass
class ReviewSession:
    audio_path: str = ""
    audio_hash: str = ""
    ref_hash: str = ""
    language: str = "auto"
    reference_raw: str = ""
    original_transcript: str = ""
    status: str = "HAS_ITEMS"
    complete: bool = False
    audio_mismatch: bool = False
    items: List[ReviewItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _kind_reason(kind: str, similarity: float) -> str:
    if kind == "uncertain":
        return f"similarity รวมต่ำ ({similarity:.2f}) — ต้องฟังด้วยหู"
    if kind == "omission":
        return "ASR ไม่พบข้อความอ้างอิงช่วงนี้ (อาจร้องไม่ชัด/เสียงเบา/ASR พลาด)"
    if kind == "insertion":
        return "ASR พบข้อความเกินจากอ้างอิง (อาจมีเสียงประสาน/เสียงปน/ASR พลาด)"
    return "ข้อความอาจคลาดเคลื่อน — ต้องฟังด้วยหู"


def build_review(report: LyricsReport, audio_path: str = "") -> ReviewSession:
    """Build a review session from a LyricsReport. Never raises."""
    audio_path = os.path.abspath(audio_path) if audio_path and os.path.isfile(audio_path) else (audio_path or "")
    current_hash = file_hash(audio_path) if audio_path and os.path.isfile(audio_path) else ""
    session = ReviewSession(
        audio_path=audio_path,
        audio_hash=current_hash,
        ref_hash=text_hash(report.reference_raw or ""),
        language=report.language or "auto",
        reference_raw=report.reference_raw or "",
        original_transcript=report.recognized_raw or "",
    )
    if report.error:
        session.status = "ASR_FAILED"
        session.warnings.append(f"วิเคราะห์เสียงไม่สำเร็จ: {report.error}")
        session.warnings.extend(report.warnings)
        return session
    if not (report.reference_raw or "").strip():
        session.status = "NO_REFERENCE"
        session.warnings.append(
            "ไม่มีเนื้อเพลงอ้างอิง — แสดงเฉพาะผลถอดเสียง "
            "ต้องไม่รายงานว่าตรวจสอบกับ reference สำเร็จ")
        session.warnings.extend(report.warnings)
        return session
    if not report.mismatches:
        session.status = "MATCH"
        session.complete = True
        session.warnings.extend(report.warnings)
        return session
    session.audio_mismatch = bool(report.audio_hash) and bool(current_hash) and (
        report.audio_hash != current_hash)
    if session.audio_mismatch:
        session.warnings.append(
            "ไฟล์เสียงไม่ตรงกับตอนวิเคราะห์ (hash เปลี่ยน) — "
            "เวลาทุกจุดถือว่าใช้ไม่ได้จนกว่าจะวิเคราะห์ใหม่")
    session.warnings.extend(report.warnings)
    for n, m in enumerate(report.mismatches, 1):
        status = _KIND_TO_STATUS.get(m.category, "POSSIBLE_MISMATCH")
        reason = _kind_reason(m.category, report.similarity)
        has_time = isinstance(m.start_time, (int, float)) and isinstance(m.end_time, (int, float))
        time_reliable = bool(has_time and report.timestamp_reliable)
        if session.audio_mismatch:
            has_time = False
            time_reliable = False
        # ALIGNMENT_UNRELIABLE only when there IS hyp text to place in time
        # but no trustworthy time exists. Empty-hyp spans (e.g. omissions)
        # keep their kind status — there is simply nothing to timestamp.
        if status != "MATCH" and not has_time and (m.hyp_text or "").strip():
            status = "ALIGNMENT_UNRELIABLE"
            reason += " | ไม่มีเวลาที่เชื่อถือได้ (—)"
        elif not report.timestamp_reliable and has_time:
            reason += " | เวลาเป็นแนวคร่าวๆ ให้ตรวจด้วยหู"
        session.items.append(ReviewItem(
            id=f"m{n}",
            kind=m.category,
            status=status,
            ref_text=m.ref_text or "",
            hyp_text=m.hyp_text or "",
            start_time=m.start_time if has_time else None,
            end_time=m.end_time if has_time else None,
            time_reliable=time_reliable,
            confidence=m.confidence,
            confidence_source="asr-word-mean" if isinstance(m.confidence, (int, float)) else "none",
            reason=reason,
        ))
    return session


def refresh_time_status(session: ReviewSession) -> ReviewSession:
    """Recompute ALIGNMENT_UNRELIABLE from current times (in place).

    Only items with non-empty hyp text are affected — empty-hyp items keep
    their kind status (nothing to place in time).
    """
    for item in session.items:
        if item.status in ("POSSIBLE_MISMATCH", "MISSING_TEXT", "EXTRA_TEXT"):
            if (item.start_time is None or item.end_time is None) and (item.hyp_text or "").strip():
                item.status = "ALIGNMENT_UNRELIABLE"
                if "เวลา" not in item.reason:
                    item.reason += " | ไม่มีเวลาที่เชื่อถือได้ (—)"
                item.time_reliable = False
    return session


def get_item(session: ReviewSession, item_id: str) -> ReviewItem:
    for item in session.items:
        if item.id == item_id:
            return item
    raise ValueError(f"Unknown review item '{item_id}'.")


def _refresh_complete(session: ReviewSession) -> None:
    session.complete = bool(session.items) and all(i.reviewed for i in session.items)


def apply_correction(session: ReviewSession, item_id: str, new_text: str,
                     actor: str = "user") -> ReviewItem:
    """Record a user edit. Original transcript is never modified."""
    item = get_item(session, item_id)
    if not isinstance(new_text, str):
        raise ValueError("Corrected text must be a string.")
    item.history.append({"actor": actor or "user", "action": "edit",
                         "prev": item.corrected_text, "new": new_text})
    item.corrected_text = new_text
    _refresh_complete(session)
    return item


def confirm_correction(session: ReviewSession, item_id: str,
                       actor: str = "user") -> ReviewItem:
    """Mark an item reviewed without changing text (original stands)."""
    item = get_item(session, item_id)
    item.history.append({"actor": actor or "user", "action": "confirm",
                         "prev": item.corrected_text,
                         "new": item.corrected_text})
    item.confirmed = True
    item.reviewed = True
    _refresh_complete(session)
    return item


def revert_correction(session: ReviewSession, item_id: str,
                      actor: str = "user") -> ReviewItem:
    """Undo to pre-edit state. Raises ValueError when nothing to undo."""
    item = get_item(session, item_id)
    if not item.history:
        raise ValueError(f"Item '{item_id}' has no edits to revert.")
    item.history.append({"actor": actor or "user", "action": "revert",
                         "prev": item.corrected_text, "new": None})
    item.corrected_text = None
    item.confirmed = False
    item.reviewed = False
    _refresh_complete(session)
    return item


def preview_corrected_text(session: ReviewSession) -> str:
    """Assemble full corrected lyrics without touching the original.

    Non-empty hyp spans are replaced in order (forward scan); corrections on
    empty-hyp items (omissions) cannot be positioned reliably and are appended
    at the end — documented approximation, see docstring limits.
    """
    text = session.original_transcript or ""
    pos = 0
    unplaced: List[str] = []
    for item in session.items:
        if item.corrected_text is None:
            continue
        old = item.hyp_text or ""
        if not old.strip():
            if item.corrected_text.strip():
                unplaced.append(item.corrected_text)
            continue
        idx = text.find(old, pos)
        if idx < 0:
            idx = text.find(old)
            if idx < 0:
                unplaced.append(item.corrected_text)
                continue
        text = text[:idx] + item.corrected_text + text[idx + len(old):]
        pos = idx + len(item.corrected_text)
    if unplaced:
        text = (text + " " + " ".join(unplaced)).strip()
    return text


def recheck_reviewed(session: ReviewSession, language: str = ""):
    """Re-compare reference vs preview (pure text, no ASR).

    Validates the TEXT-level effect of corrections only — not audio quality.
    """
    if not (session.reference_raw or "").strip():
        raise ValueError("Cannot recheck without reference lyrics.")
    return compare_lyrics(session.reference_raw,
                          preview_corrected_text(session),
                          language or session.language or "auto")


def save_session(session: ReviewSession, path: str) -> str:
    """Persist session JSON (sidecar pattern). Returns the path written."""
    payload = {
        "version": REVIEW_VERSION,
        "audio_path": session.audio_path,
        "audio_hash": session.audio_hash,
        "ref_hash": session.ref_hash,
        "language": session.language,
        "reference_raw": session.reference_raw,
        "original_transcript": session.original_transcript,
        "status": session.status,
        "complete": session.complete,
        "audio_mismatch": session.audio_mismatch,
        "warnings": list(session.warnings),
        "items": [
            {
                "id": i.id, "kind": i.kind, "status": i.status,
                "ref_text": i.ref_text, "hyp_text": i.hyp_text,
                "corrected_text": i.corrected_text,
                "start_time": i.start_time, "end_time": i.end_time,
                "time_reliable": i.time_reliable,
                "confidence": i.confidence,
                "confidence_source": i.confidence_source,
                "reason": i.reason, "reviewed": i.reviewed,
                "confirmed": i.confirmed, "history": list(i.history),
            }
            for i in session.items
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_session(path: str) -> ReviewSession:
    """Load a session saved by save_session. Raises on corrupt files."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    session = ReviewSession(
        audio_path=raw.get("audio_path", ""),
        audio_hash=raw.get("audio_hash", ""),
        ref_hash=raw.get("ref_hash", ""),
        language=raw.get("language", "auto"),
        reference_raw=raw.get("reference_raw", ""),
        original_transcript=raw.get("original_transcript", ""),
        status=raw.get("status", "HAS_ITEMS"),
        complete=bool(raw.get("complete", False)),
        audio_mismatch=bool(raw.get("audio_mismatch", False)),
        warnings=list(raw.get("warnings", [])),
    )
    for r in raw.get("items", []):
        session.items.append(ReviewItem(
            id=r.get("id", ""), kind=r.get("kind", ""),
            status=r.get("status", "POSSIBLE_MISMATCH"),
            ref_text=r.get("ref_text", ""), hyp_text=r.get("hyp_text", ""),
            corrected_text=r.get("corrected_text"),
            start_time=r.get("start_time"), end_time=r.get("end_time"),
            time_reliable=bool(r.get("time_reliable", False)),
            confidence=r.get("confidence"),
            confidence_source=r.get("confidence_source", "none"),
            reason=r.get("reason", ""), reviewed=bool(r.get("reviewed", False)),
            confirmed=bool(r.get("confirmed", False)),
            history=list(r.get("history", [])),
        ))
    return session


def session_to_dict(session: ReviewSession) -> dict:
    """JSON-safe dict for Gradio State transport."""
    return {
        "audio_path": session.audio_path, "audio_hash": session.audio_hash,
        "ref_hash": session.ref_hash, "language": session.language,
        "reference_raw": session.reference_raw,
        "original_transcript": session.original_transcript,
        "status": session.status, "complete": session.complete,
        "audio_mismatch": session.audio_mismatch,
        "warnings": list(session.warnings),
        "items": [
            {"id": i.id, "kind": i.kind, "status": i.status,
             "ref_text": i.ref_text, "hyp_text": i.hyp_text,
             "corrected_text": i.corrected_text,
             "start_time": i.start_time, "end_time": i.end_time,
             "time_reliable": i.time_reliable, "confidence": i.confidence,
             "confidence_source": i.confidence_source, "reason": i.reason,
             "reviewed": i.reviewed, "confirmed": i.confirmed,
             "history": list(i.history)}
            for i in session.items
        ],
    }


def session_from_dict(raw: dict) -> ReviewSession:
    """Rebuild a session from session_to_dict output."""
    session = ReviewSession(
        audio_path=raw.get("audio_path", ""),
        audio_hash=raw.get("audio_hash", ""),
        ref_hash=raw.get("ref_hash", ""),
        language=raw.get("language", "auto"),
        reference_raw=raw.get("reference_raw", ""),
        original_transcript=raw.get("original_transcript", ""),
        status=raw.get("status", "HAS_ITEMS"),
        complete=bool(raw.get("complete", False)),
        audio_mismatch=bool(raw.get("audio_mismatch", False)),
        warnings=list(raw.get("warnings", [])),
    )
    for r in raw.get("items", []):
        session.items.append(ReviewItem(
            id=r.get("id", ""), kind=r.get("kind", ""),
            status=r.get("status", "POSSIBLE_MISMATCH"),
            ref_text=r.get("ref_text", ""), hyp_text=r.get("hyp_text", ""),
            corrected_text=r.get("corrected_text"),
            start_time=r.get("start_time"), end_time=r.get("end_time"),
            time_reliable=bool(r.get("time_reliable", False)),
            confidence=r.get("confidence"),
            confidence_source=r.get("confidence_source", "none"),
            reason=r.get("reason", ""), reviewed=bool(r.get("reviewed", False)),
            confirmed=bool(r.get("confirmed", False)),
            history=list(r.get("history", [])),
        ))
    return session


def check_stale(session: ReviewSession, audio_path: str = "", reference: str = "") -> bool:
    """True when the session no longer matches the given audio/reference."""
    if audio_path and session.audio_hash:
        if session.audio_hash != file_hash(audio_path):
            return True
    if reference is not None and session.ref_hash != text_hash(reference or ""):
        return True
    return False


def validate_item_audio(session: ReviewSession, item_id: str) -> List[str]:
    """Validate one item's time against its audio file. Returns issue list.

    Checks: file exists, duration bounds (via clamp), suspiciously short
    spans, silent spans. Out-of-range times are invalidated (set to None).
    Never raises.
    """
    issues: List[str] = []
    try:
        item = get_item(session, item_id)
    except ValueError as e:
        return [str(e)]
    path = session.audio_path or ""
    if not path or not os.path.isfile(path):
        issues.append("หาไฟล์เสียงไม่พบ — ตรวจขอบเขตเวลาไม่ได้")
        return issues
    try:
        from .postrvc import audio_info, clamp_segment
        info = audio_info(path)
    except Exception as e:
        issues.append(f"อ่านไฟล์เสียงไม่ได้: {e}")
        return issues
    duration = info["duration_sec"]
    if item.start_time is not None and item.end_time is not None:
        seg = clamp_segment(item.start_time, item.end_time, duration)
        if seg["clamped"]:
            issues.append(
                f"เวลาอยู่นอกขอบเขตไฟล์ ({duration:.1f}s) — ถือว่าใช้ไม่ได้")
            item.start_time = None
            item.end_time = None
            item.time_reliable = False
            refresh_time_status(session)
        elif seg["end"] - seg["start"] < 0.15:
            issues.append("ช่วงเสียงสั้นกว่า 0.15s — อาจตัดคำ ฟังด้วยความระวัง")
        else:
            try:
                import soundfile as sfx
                import numpy as np
                with sfx.SoundFile(path) as f:
                    f.seek(int(seg["start"] * info["sample_rate"]))
                    data = f.read(int((seg["end"] - seg["start"]) * info["sample_rate"]),
                                  dtype="float32", always_2d=True)
                mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
                rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
                if rms < 0.001:
                    issues.append("ช่วงนี้เงียบ (≈ silence) — timestamp อาจไม่ตรงคำร้อง")
            except ImportError:
                issues.append("ตรวจ silence ไม่ได้ (ขาด soundfile)")
            except Exception as e:
                issues.append(f"ตรวจช่วงเสียงไม่ได้: {e}")
    if session.audio_mismatch:
        issues.append("ไฟล์เสียงไม่ตรงกับตอนวิเคราะห์ — เวลาใช้ไม่ได้")
    return issues
