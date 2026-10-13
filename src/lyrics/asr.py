"""ASR backend (faster-whisper only). Lazy import so the WebUI works without the dep."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from .compare import AUTO_LANGUAGE, validate_language

SUPPORTED_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3-turbo")
DEFAULT_MODEL_SIZE = "base"
SUPPORTED_AUDIO_EXTS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff",
}

_MODEL_CACHE: dict = {}


class ASRError(Exception):
    pass


class AudioValidationError(ASRError):
    pass


class ModelLoadError(ASRError):
    pass


# Re-export for callers that catch it from here.
from .compare import UnsupportedLanguageError  # noqa: E402,F401


@dataclass
class TranscriptionResult:
    text: str = ""
    segments: List[dict] = field(default_factory=list)
    language: str = ""
    language_probability: Optional[float] = None


def validate_audio(audio_path: str) -> str:
    if not audio_path or not isinstance(audio_path, str):
        raise AudioValidationError("Audio path must be a non-empty string.")
    if not os.path.isfile(audio_path):
        raise AudioValidationError(f"Audio file does not exist: {audio_path}")
    ext = os.path.splitext(audio_path)[1].lower()
    if ext not in SUPPORTED_AUDIO_EXTS:
        raise AudioValidationError(
            f"Unsupported audio format '{ext or '(none)'}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_AUDIO_EXTS))}."
        )
    return os.path.abspath(audio_path)


def _compute_type_for(device: str) -> str:
    return "float16" if device == "cuda" else "int8"


def get_model(model_size: str = DEFAULT_MODEL_SIZE, device: str = "cpu"):
    """Lazy singleton per (size, device). Raises ModelLoadError with a clear message."""
    size = (model_size or DEFAULT_MODEL_SIZE).strip()
    if size not in SUPPORTED_MODEL_SIZES:
        raise ModelLoadError(
            f"Unknown model size '{model_size}'. Choose from: {', '.join(SUPPORTED_MODEL_SIZES)}."
        )
    dev = (device or "cpu").strip().lower()
    if dev not in ("cpu", "cuda"):
        raise ModelLoadError("Device must be 'cpu' or 'cuda'.")
    key = (size, dev)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ModelLoadError(
            "faster-whisper is not installed. Install it with: "
            "pip install faster-whisper  (optional dependency for Lyrics Checker only)."
        ) from e
    try:
        model = WhisperModel(size, device=dev, compute_type=_compute_type_for(dev))
    except Exception as e:
        raise ModelLoadError(f"Could not load ASR model '{size}' on '{dev}': {e}") from e
    _MODEL_CACHE[key] = model
    return model


def unload_models() -> None:
    """Free cached ASR models (e.g. before RVC needs VRAM)."""
    _MODEL_CACHE.clear()


def transcribe(
    audio_path: str,
    language: str = "auto",
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = "cpu",
    word_timestamps: bool = True,
    vad_filter: bool = False,
) -> TranscriptionResult:
    """Transcribe vocals; word timestamps included when the backend supports them.

    vad_filter defaults to False: Silero VAD is tuned for speech and tends to
    strip out sung vocals, leaving near-empty transcripts.
    """
    path = validate_audio(audio_path)
    lang = validate_language(language)
    lang_arg: Optional[str] = None if lang == AUTO_LANGUAGE else lang
    model = get_model(model_size, device)
    # F.5 note: decoding uses faster-whisper defaults deliberately (beam_size=5
    # with temperature fallback 0.0→1.0). The fallback keeps sung, low-confidence
    # passages transcribable; as a trade-off, transcripts may differ slightly
    # between runs — never claim 100% repeatability. Do not disable the fallback
    # or pin temperature without re-evaluating singing quality.
    try:
        segments_iter, info = model.transcribe(
            path,
            language=lang_arg,
            word_timestamps=word_timestamps,
            vad_filter=vad_filter,
        )
    except Exception as e:
        raise ASRError(f"Transcription failed: {e}") from e
    texts: List[str] = []
    segments: List[dict] = []
    for seg in segments_iter:
        texts.append(seg.text or "")
        words = []
        for w in (getattr(seg, "words", None) or []):
            words.append(
                {
                    "word": getattr(w, "word", ""),
                    "start": getattr(w, "start", None),
                    "end": getattr(w, "end", None),
                    "probability": getattr(w, "probability", None),
                }
            )
        segments.append(
            {"text": seg.text or "", "start": seg.start, "end": seg.end, "words": words}
        )
    return TranscriptionResult(
        text=" ".join(t.strip() for t in texts).strip(),
        segments=segments,
        language=getattr(info, "language", "") or "",
        language_probability=getattr(info, "language_probability", None),
    )
