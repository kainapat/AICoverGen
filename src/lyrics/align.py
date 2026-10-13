"""Word-timestamp helpers with explicit fallback when alignment is unreliable.

Granularity contract (Phase 2):
  "word"    — every timestamped mismatch has real word-level times.
  "segment" — at least one mismatch falls back to real segment times.
  "none"    — no trustworthy times; callers must render "—".
Never invent times by uniformly dividing song length by word count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass
class WordSegment:
    word: str
    start: Optional[float] = None
    end: Optional[float] = None
    probability: Optional[float] = None


@dataclass
class SegmentInfo:
    text: str = ""
    start: Optional[float] = None
    end: Optional[float] = None


def build_words_from_segments(segments: Sequence[dict]) -> List[WordSegment]:
    """Flatten faster-whisper style segments [{..., 'words': [{word,start,end,probability}]}]."""
    words: List[WordSegment] = []
    for seg in segments or []:
        for w in (seg.get("words") or []):
            words.append(
                WordSegment(
                    word=str(w.get("word", "")).strip(),
                    start=w.get("start"),
                    end=w.get("end"),
                    probability=w.get("probability"),
                )
            )
    return words


def build_segments_from_raw(segments: Sequence[dict]) -> List[SegmentInfo]:
    """Extract real segment times (no word detail needed)."""
    out: List[SegmentInfo] = []
    for seg in segments or []:
        out.append(
            SegmentInfo(
                text=str(seg.get("text", "") or ""),
                start=seg.get("start"),
                end=seg.get("end"),
            )
        )
    return out


def _norm_search(text: str) -> str:
    return " ".join((text or "").lower().split())


def _find_segment_span(hyp_text: str, segments: Sequence[SegmentInfo]):
    """Find real segment times containing hyp_text. Returns (start, end) or (None, None)."""
    key = _norm_search(hyp_text)
    if not key or not segments:
        return None, None
    hits = []
    for seg in segments:
        hay = _norm_search(seg.text)
        if key and key in hay and isinstance(seg.start, (int, float)) and isinstance(seg.end, (int, float)):
            hits.append(seg)
    if not hits:
        # Fallback: first-token containment (handles chunked Thai).
        first = key.split(" ")[0] if key.split(" ") else ""
        if len(first) >= 2:
            for seg in segments:
                hay = _norm_search(seg.text)
                if first in hay and isinstance(seg.start, (int, float)) and isinstance(seg.end, (int, float)):
                    hits.append(seg)
    if not hits:
        return None, None
    return min(s.start for s in hits), max(s.end for s in hits)


def attach_timestamps_with_granularity(
    mismatches,
    words: Sequence[WordSegment] = (),
    segments: Sequence[SegmentInfo | dict] = (),
) -> Tuple[bool, str]:
    """Fill start/end times; return (reliable, granularity).

    granularity is "word" | "segment" | "none". Word-level is tried first;
    mismatches without valid word times fall back to real segment times via
    text search. Times are never synthesized by uniform division.
    Mutates mismatches in place.
    """
    words = list(words or [])
    segs: List[SegmentInfo] = []
    for s in segments or []:
        if isinstance(s, SegmentInfo):
            segs.append(s)
        elif isinstance(s, dict):
            segs.append(SegmentInfo(text=str(s.get("text", "") or ""), start=s.get("start"), end=s.get("end")))
    if not mismatches:
        return False, "none"
    used_segment = False
    reliable = True
    has_word_table = bool(words)
    for m in mismatches:
        span = words[m.hyp_start : m.hyp_end] if (has_word_table and m.hyp_end > m.hyp_start) else []
        if span:
            starts = [w.start for w in span if isinstance(w.start, (int, float))]
            ends = [w.end for w in span if isinstance(w.end, (int, float))]
            if len(starts) == len(span) and len(ends) == len(span):
                m.start_time = min(starts)
                m.end_time = max(ends)
                continue
        # Word-level missing/partial → try real segment times.
        if m.hyp_end > m.hyp_start and (m.hyp_text or "").strip() and segs:
            s, e = _find_segment_span(m.hyp_text, segs)
            if s is not None and e is not None:
                m.start_time = s
                m.end_time = e
                used_segment = True
                continue
        m.start_time = None
        m.end_time = None
        if m.category in ("substitution", "insertion", "uncertain"):
            reliable = False
    if reliable and not used_segment and has_word_table:
        return True, "word"
    if used_segment:
        # Segment fallback in use: times are real but coarser.
        any_times = any(isinstance(m.start_time, (int, float)) for m in mismatches)
        return (reliable and any_times), "segment"
    return False, "none"


def attach_timestamps(mismatches, words: Sequence[WordSegment] = (), segments=None) -> bool:
    """Fill start/end times on mismatches from hyp token indices.

    Returns True only if every timestamped mismatch has valid times
    (timestamp_reliable). Missing/partial times -> None + returns False.
    Mutates mismatches in place. `segments` enables Phase 2 segment fallback.
    """
    reliable, _ = attach_timestamps_with_granularity(mismatches, words, segments or ())
    return reliable
