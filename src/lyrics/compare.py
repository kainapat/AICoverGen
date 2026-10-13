"""Text normalization and lyric comparison (pure functions, no model required)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Literal, Optional

MismatchCategory = Literal["substitution", "omission", "insertion", "uncertain"]

SUPPORTED_LANGUAGES = {
    "th": "Thai",
    "en": "English",
}
# Extensible without touching core logic: use register_language(),
# e.g. register_language("ja", "Japanese"). Direct dict edits still work.
EXTRA_LANGUAGES: dict = {}
AUTO_LANGUAGE = "auto"

# Per-language text rules. Each entry may define:
#   "normalizer": Callable[[str], str]  (NFKC/zero-width already handled by caller
#                only when using normalize_text(); custom normalizers receive raw text)
#   "tokenizer": Callable[[str], List[str]]
#   "spaceless": bool — True when the script does not separate every word with
#                spaces (Thai). Comparisons stay chunk-based and mismatches must
#                be reported as suspicions, never as certain word errors.
_LANGUAGE_RULES: dict = {}


def register_language(code: str, name: str, normalizer=None, tokenizer=None, spaceless: bool = False) -> None:
    """Register an extra language without touching core comparison logic."""
    c = (code or "").strip().lower()
    if not c or c == AUTO_LANGUAGE:
        raise ValueError("Language code must be a non-empty string other than 'auto'.")
    EXTRA_LANGUAGES[c] = name or c
    if normalizer is not None or tokenizer is not None or spaceless:
        _LANGUAGE_RULES[c] = {
            "normalizer": normalizer,
            "tokenizer": tokenizer,
            "spaceless": bool(spaceless),
        }


def is_spaceless_language(language: str) -> bool:
    lang = (language or "").strip().lower()
    if lang == "th":
        return True
    return bool(_LANGUAGE_RULES.get(lang, {}).get("spaceless", False))


def get_language_rules(language: str) -> dict:
    return dict(_LANGUAGE_RULES.get((language or "").strip().lower(), {}))


class UnsupportedLanguageError(ValueError):
    pass


def supported_languages() -> dict:
    return {**SUPPORTED_LANGUAGES, **EXTRA_LANGUAGES}


def validate_language(language: str) -> str:
    lang = (language or "").strip().lower()
    if lang == AUTO_LANGUAGE:
        return lang
    if lang not in supported_languages():
        raise UnsupportedLanguageError(
            f"Unsupported language '{language}'. "
            f"Supported: auto, {', '.join(sorted(supported_languages()))}."
        )
    return lang


@dataclass
class Mismatch:
    category: MismatchCategory
    ref_text: str = ""
    hyp_text: str = ""
    ref_start: int = 0
    ref_end: int = 0
    hyp_start: int = 0
    hyp_end: int = 0
    # Mean ASR word probability over the verified span, or None when unknown.
    # Never the global similarity (see CompareResult.similarity instead).
    confidence: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None


@dataclass
class CompareResult:
    mismatches: List[Mismatch] = field(default_factory=list)
    similarity: float = 1.0
    norm_ref: str = ""
    norm_hyp: str = ""
    ref_tokens: List[str] = field(default_factory=list)
    hyp_tokens: List[str] = field(default_factory=list)


_PUNCT_RE = re.compile(r"[^\w\s\u0E00-\u0E7F]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)
_ZW_RE = re.compile(r"[\u200b-\u200d\ufeff]")

# Thai (and other spaceless scripts) can produce a whole song as ONE token,
# which renders as a single unreadable row. Split long tokens into chunks…
MAX_CHUNK_CHARS = 60
# …and split a single replace/delete/insert spanning more than this many
# chunks into several mismatches, so no report row ever holds half a song.
PER_MISMATCH_CHUNKS = 4


def chunk_long_tokens(tokens: List[str], max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    out: List[str] = []
    for tok in tokens:
        if len(tok) <= max_chars:
            out.append(tok)
        else:
            out.extend(tok[i : i + max_chars] for i in range(0, len(tok), max_chars))
    return out


def _normalize_generic_core(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = _ZW_RE.sub("", t)
    t = t.lower()
    # Remove punctuation outright (not replaced with space): Thai has no
    # inter-word spaces, so "..." -> " " would create a false mismatch.
    t = _PUNCT_RE.sub("", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def _normalize_th(text: str) -> str:
    """Thai: NFKC + zero-width strip + lowercase (no-op for Thai) + punct drop.

    Keeps single spaces as-is; does NOT try to re-segment words. Spaceless
    Thai therefore diffs on chunks (see tokenize_for_language) and every
    mismatch is only a suspicion, never a certain word error.
    """
    return _normalize_generic_core(text)


def _normalize_en(text: str) -> str:
    """English: case-insensitive, punctuation-insensitive."""
    return _normalize_generic_core(text)


def normalize_text(text: str, language: str = "auto") -> str:
    """NFKC + strip zero-width + drop punctuation + collapse whitespace.

    Punctuation differences never produce mismatches by themselves.
    Dispatches to a per-language normalizer when registered; th/en fall back
    to rules that are identical today but remain independently overridable.
    """
    if not isinstance(text, str):
        raise ValueError("Lyrics must be a string.")
    validate_language(language)
    lang = (language or "").strip().lower()
    rules = _LANGUAGE_RULES.get(lang, {})
    fn = rules.get("normalizer")
    if callable(fn):
        return fn(text)
    if lang == "th":
        return _normalize_th(text)
    if lang == "en":
        return _normalize_en(text)
    return _normalize_generic_core(text)


def tokenize(normalized: str) -> List[str]:
    return normalized.split() if normalized else []


def tokenize_for_language(normalized: str, language: str = "auto") -> List[str]:
    """Split normalized text into diff tokens for the given language.

    Thai (spaceless) keeps whitespace splits then chunks long tokens so a
    whole song never becomes one unreadable row. No new dependency; word
    boundaries in spaceless text remain approximate — see THAI_LIMITATION.
    """
    validate_language(language)
    lang = (language or "").strip().lower()
    rules = _LANGUAGE_RULES.get(lang, {})
    fn = rules.get("tokenizer")
    if callable(fn):
        return chunk_long_tokens(list(fn(normalized) or []))
    return chunk_long_tokens(tokenize(normalized))


THAI_LIMITATION = (
    "ภาษาไทยไม่เว้นวรรคทุกคำ การเปรียบเทียบจึงทำบนชิ้นข้อความ (chunk) "
    "ไม่ใช่คำที่ตัดถูกต้องเสมอไป ห้ามตัดสินว่าคำไทยหาย/ผิดจากการ split() "
    "เพียงอย่างเดียว ความต่างทุกจุดคือข้อสงสัยให้ตรวจด้วยหู"
)


def compare_lyrics(
    reference: str,
    recognized: str,
    language: str = "auto",
    uncertain_threshold: float = 0.5,
) -> CompareResult:
    """Diff reference vs recognized lyrics; classify sub/omission/insertion.

    Raises ValueError on invalid inputs, UnsupportedLanguageError on bad language.
    """
    if not isinstance(reference, str) or not isinstance(recognized, str):
        raise ValueError("Reference and recognized lyrics must be strings.")
    validate_language(language)
    norm_ref = normalize_text(reference, language)
    norm_hyp = normalize_text(recognized, language)
    if not norm_ref and not norm_hyp:
        raise ValueError("Both reference and recognized lyrics are empty.")
    ref_tokens = tokenize_for_language(norm_ref, language)
    hyp_tokens = tokenize_for_language(norm_hyp, language)
    matcher = SequenceMatcher(a=ref_tokens, b=hyp_tokens, autojunk=False)
    similarity = float(matcher.ratio())
    mismatches: List[Mismatch] = []

    def emit(
        cat: MismatchCategory,
        ri1: int,
        ri2: int,
        hj1: int,
        hj2: int,
    ) -> None:
        # F.3: confidence stays None here. The global similarity is NOT a
        # per-word confidence; ASR word probabilities are attached later by
        # attach_timestamps_with_granularity() only for verified word spans.
        # The aggregate stays available as CompareResult.similarity.
        mismatches.append(
            Mismatch(
                category=cat,
                ref_text=" ".join(ref_tokens[ri1:ri2]),
                hyp_text=" ".join(hyp_tokens[hj1:hj2]),
                ref_start=ri1,
                ref_end=ri2,
                hyp_start=hj1,
                hyp_end=hj2,
                confidence=None,
            )
        )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            cat: MismatchCategory = (
                "uncertain" if similarity < uncertain_threshold and (i2 - i1) > 3 else "substitution"
            )
        elif tag == "delete":
            cat = "omission"
        else:
            cat = "insertion"
        # Split wide spans so each mismatch stays a small readable row.
        ri, hj = i1, j1
        while ri < i2 or hj < j2:
            ri2 = min(ri + PER_MISMATCH_CHUNKS, i2) if ri < i2 else ri
            hj2 = min(hj + PER_MISMATCH_CHUNKS, j2) if hj < j2 else hj
            emit(cat, ri, ri2, hj, hj2)
            ri, hj = ri2, hj2
    return CompareResult(
        mismatches=mismatches,
        similarity=similarity,
        norm_ref=norm_ref,
        norm_hyp=norm_hyp,
        ref_tokens=ref_tokens,
        hyp_tokens=hyp_tokens,
    )
