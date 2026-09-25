# 20. Pre-cleaning Pipeline for Song Metadata Extraction

Date: 2026-09-25

## Status

Accepted

## Context

When users process YouTube URLs such as `https://youtu.be/2OZktFecG_g` (`ZENTYARB - ฉบับท้ายสุด (Prod. by TRILOGY) [Official MV]`), the metadata extraction function `extract_song_and_artist()` produced a corrupted title:
`TRILOGY) [ MV] - ZENTYARB - ฉบับท้ายสุด (Prod`

### Root Cause
1. `extract_song_and_artist()` checked the regex pattern `r'^[《【\[(]?\s*(.*?)\s*[》】\])]?\s*(?:by|โดย)\s+(.+)$'` on the raw title before cleaning promotional noise or producer credits.
2. The keyword `by` inside `(Prod. by TRILOGY)` caused the regex to greedily match the rest of the string as the artist name (`TRILOGY) [Official MV]`), while treating `ZENTYARB - ฉบับท้ายสุด (Prod.` as the song title.
3. Subsequent inversion and formatting logic treated `TRILOGY) [ MV]` as the leading artist, completely breaking the user interface display and output filename.

## Decision

1. **Pre-clean First**: Run `clean_song_title(title_norm)` at the very top of `extract_song_and_artist()`. All bracketed producer tags (`(Prod. by ...)`, `[PROD. BY ...]`), delimited producer tags (`- Prod. by ...`), and video noise (`[Official MV]`, `[ MV]`, `[M/V]`) are stripped before any syntactic pattern matching begins.
2. **Constrain Song-by-Artist Pattern**: Guard the `by_match` pattern so it only evaluates if the cleaned title does not already contain an explicit `' - '` artist-song separator.
3. **Preserve Legitimate Titles**: Ensure normal vocabulary beginning with `prod` (such as `Product of Love` or `Prodigy`) remains intact.

## Consequences

- YouTube titles containing `(Prod. by ...)` and video tags are cleanly parsed as `[Artist] - [Song]` (e.g. `ZENTYARB - ฉบับท้ายสุด`).
- The WebUI input textbox and the output cover filename `<Artist> - <Song> (<Model> Ver).mp3` match accurately without orphaned brackets or distorted credits.
- `extract_song_and_artist()` is fully deterministic and covered by automated regression tests in `tests/test_clean_song_title.py`.
