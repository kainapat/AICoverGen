"""Word-timestamp helpers with explicit fallback when alignment is unreliable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass
class WordSegment:
    word: str
    start: Optional[float] = None
    end: Optional[float] = None
    probability: Optional[float] = None


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


def attach_timestamps(mismatches, words: Sequence[WordSegment]) -> bool:
    """Fill start/end times on mismatches from hyp token indices.

    Returns True only if every timestamped mismatch has valid times
    (timestamp_reliable). Missing/partial times -> None + returns False.
    Mutates mismatches in place.
    """
    words = list(words or [])
    if not mismatches:
        return False
    if not words:
        return False
    reliable = True
    for m in mismatches:
        span = words[m.hyp_start : m.hyp_end] if m.hyp_end > m.hyp_start else []
        if not span:
            m.start_time = None
            m.end_time = None
            if m.category in ("substitution", "insertion", "uncertain"):
                reliable = False
            continue
        starts = [w.start for w in span if isinstance(w.start, (int, float))]
        ends = [w.end for w in span if isinstance(w.end, (int, float))]
        if len(starts) == len(span) and len(ends) == len(span):
            m.start_time = min(starts)
            m.end_time = max(ends)
        else:
            m.start_time = None
            m.end_time = None
            reliable = False
    return reliable
