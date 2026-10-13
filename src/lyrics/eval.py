"""Phase 5 — measurable audio/lyrics evaluation helpers (no model needed).

All metrics have explicit definitions and limits. Signal metrics (peak, rms,
silence, clipping) describe LEVELS, never naturalness, accent, timbre
similarity, or pronunciation quality. Transcript metrics describe ASR
recognizability, never ground-truth lyric accuracy.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Tuple

from .report import LyricsReport


def alignment_stats(report: LyricsReport) -> Dict[str, Any]:
    """Count timed vs untimed mismatches and confidence coverage.

    timed_ratio = timed / total (1.0 when there is nothing to time).
    confidence_* describe ASR word-probability availability, not correctness.
    """
    total = len(report.mismatches)
    timed = sum(1 for m in report.mismatches
                if isinstance(m.start_time, (int, float))
                and isinstance(m.end_time, (int, float)))
    confs = [m.confidence for m in report.mismatches
             if isinstance(m.confidence, (int, float))]
    return {
        "total": total,
        "timed": timed,
        "untimed": total - timed,
        "timed_ratio": (timed / total) if total else 1.0,
        "granularity": report.timestamp_granularity,
        "reliable": bool(report.timestamp_reliable),
        "confidence_coverage": (len(confs) / total) if total else 0.0,
        "confidence_mean": (sum(confs) / len(confs)) if confs else None,
    }


def measure_runtime(fn: Callable, *args, **kwargs) -> Tuple[Any, Dict[str, Any]]:
    """Run fn and report wall time plus CUDA peak (when torch+CUDA exist).

    `cuda_peak_mb` tracks the TORCH allocator delta only. Backends that manage
    their own CUDA memory (e.g. ctranslate2 used by faster-whisper) do NOT show
    up here — use nvidia-smi for whole-GPU numbers. 0.0 therefore means "no
    extra torch allocation", not "no VRAM used".
    Exceptions propagate. Never imports torch at module level.
    """
    cuda_available = False
    peak_before: Any = None
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            torch.cuda.reset_peak_memory_stats()
            peak_before = torch.cuda.max_memory_allocated()
    except Exception:
        cuda_available = False
    start = time.perf_counter()
    out = fn(*args, **kwargs)
    seconds = time.perf_counter() - start
    peak_mb = None
    if cuda_available:
        try:
            import torch
            peak_after = torch.cuda.max_memory_allocated()
            peak_mb = round((peak_after - (peak_before or 0)) / (1024 * 1024), 2)
        except Exception:
            peak_mb = None
    return out, {"seconds": seconds, "cuda_available": cuda_available,
                 "cuda_peak_mb": peak_mb}


def format_metrics_block(info: Dict[str, Any], quality: Dict[str, Any],
                         stats: Dict[str, Any]) -> str:
    """Markdown block with definitions baked in (self-documenting report)."""
    flags = "; ".join(quality.get("flags", [])) or "ปกติ / no flags"
    conf = (f"{stats['confidence_mean']:.2f} (coverage {stats['confidence_coverage']:.0%})"
            if stats.get("confidence_mean") is not None else "ไม่มีข้อมูล / none")
    return "\n".join([
        f"- ไฟล์: {info.get('duration_sec', 0):.1f}s, "
        f"{info.get('sample_rate', '?')} Hz, {info.get('channels', '?')} ch",
        f"- ระดับสัญญาณ: peak {quality.get('peak', 0):.3f} (1.0 = full scale), "
        f"rms {quality.get('rms', 0):.4f}, clip {quality.get('clipping_ratio', 0):.2%}, "
        f"เงียบ {quality.get('silent_ratio', 0):.0%} → {flags}",
        f"- การจัดแนว: {stats.get('timed', 0)}/{stats.get('total', 0)} จุดมีเวลา "
        f"({stats.get('timed_ratio', 0):.0%}), ระดับ {stats.get('granularity')}, "
        f"confidence {conf}",
        "- หมายเหตุ: ตัวเลขข้างต้นวัดระดับสัญญาณและการรู้จำของ ASR เท่านั้น "
        "ไม่ได้รับประกัน naturalness, สำเนียง, ความเหมือนเสียงร้อง หรือความถูกต้องของเนื้อเพลง",
    ])
