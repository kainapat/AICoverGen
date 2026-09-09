# Smart Song-Artist Inversion and Extended Promotional Noise Filtering

We automatically detect and correct inverted YouTube video titles (`[Song Title] - [Artist Name]`) by cross-referencing with the channel identity, and expand promotional noise filters to comprehensively eliminate `Official Lyrics Video` and pipe-enclosed tags (`|...|`).

**Context & Problem:**
Certain music channels and creators on YouTube title their video uploads with the song title first, followed by the artist name (e.g. `โฆษณาชวนเลือก - TaitosmitH |Official Lyrics Video|` on channel `TAITOSMITH OFFICIAL`).
1. **Inverted Metadata:** For video uploads lacking dedicated `track` and `artist` metadata tags, naive hyphen splitting (`part1, part2 = title.split(' - ', 1)`) assumed `part1` was the artist and `part2` was the song, producing reversed filenames (`โฆษณาชวนเลือก - TaitosmitH`).
2. **Unstripped Noise Tags:** Earlier regex filters targeted singular `lyric\s*video` and bracketed noise, failing to catch plural `Official Lyrics Video`, pipe-wrapped promo tags (`|Official Lyrics Video|`), and unbracketed trailing promotional text.

**Considered Options:**
- Hardcode channel overrides — rejected: High maintenance and fragile; does not generalize across artists.
- Always require user to manually fix the title in the WebUI — rejected: Degrades user experience; users expect the automation to handle standard channel uploads intelligently.
- Channel-aware Song-Artist Inversion Detection & Extended Regex — accepted:
  1. Compare `part1` and `part2` against `clean_channel_name(raw_artist or raw_channel)`. If `part2` matches the channel identity and `part1` does not, swap them so `artist = part2` and `song = part1`.
  2. Update `clean_song_title` regex patterns to match `lyrics?\s*video` (singular/plural), pipe-bound promo blocks (`\|\s*[^|]*(?:official|music|video|audio|mv|lyrics?|visualizer)[^|]*\|?`), and trailing unbracketed suffixes.
  3. Combine with existing CJK Romanization and `Feat.` clause parsing.

**Consequences:**
- Videos titled as `[Song] - [Artist]` are automatically reordered to the international standard `[Artist] - [Song]` (e.g. `TaitosmitH - โฆษณาชวนเลือก`).
- Titles with `Official Lyrics Video`, `|...|` pipes, and visualizer suffixes are completely cleaned.
- Fully backwards-compatible with standard `[Artist] - [Song]` tracks and non-channel uploads.
