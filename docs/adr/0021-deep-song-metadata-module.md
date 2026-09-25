# 21. Deep SongMetadata Module

Date: 2026-09-25

## Status

Accepted

## Context

Prior to this decision, song title cleaning, Unicode normalization, promotional noise stripping, CJK romanization, featured artist extraction, and smart song-artist inversion were exposed as 6 independent free functions in `src/main.py` (`clean_song_title`, `clean_channel_name`, `parse_feat_clause`, `resolve_feat_artist`, `resolve_artist_name`, `extract_song_and_artist`).

This shallow cluster caused architectural friction:
1. **Ordering & State Leakage**: Callers had to know the exact internal order in which to run sanitization steps (e.g. `clean_song_title` before grammar pattern matching), directly causing the producer credit parsing bug.
2. **Scattered Seam**: Both `main.py` and `webui.py` invoked different parts of the cluster directly, duplicating assumptions about Unicode and fallback channel names.
3. **Test Surface**: Tests could bypass the primary interface and test intermediate private transformations, failing to exercise the true user-facing seam.

## Decision

1. **Encapsulate in a Deep Module (`src/song_metadata.py`)**:
   - Provide a single, deep immutable class `SongMetadata` with a minimal interface: `SongMetadata.from_input(info_or_title, channel_fallback=None)`.
   - Hide all normalization, regex de-noising, CJK romanization via `pykakasi`/`kroman`, and inversion logic inside the private `SongMetadataNormalizer` implementation.
2. **Single Seam**:
   - Callers (`yt_download`, `webui.py`, pipeline output naming) pass raw inputs (string filename or yt-dlp metadata dictionary) and receive a structured `SongMetadata` object exposing `.formatted_title`, `.title`, `.artist`, and `.featured_artist`.
3. **Preserve Re-exports for Backward Compatibility**:
   - Re-export legacy functions in `src/main.py` as delegates to `SongMetadataNormalizer` to protect external scripts and CLI callers.

## Consequences

- The interface shrinks from 6 loose functions to 1 cohesive class constructor.
- Parsing and sanitization bugs now concentrate with 100% locality in `src/song_metadata.py`.
- Callers and tests exercise the same seam (`SongMetadata.from_input`).
