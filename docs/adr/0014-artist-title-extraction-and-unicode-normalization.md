# Artist-Title Extraction and NFKC Unicode Normalization

We standardize song metadata extracted from YouTube and YouTube Music into the international format `[Artist] - [Song Title]` using NFKC Unicode normalization and smart deduplication.

**Context & Problem:**
Previously, `clean_song_title()` only took the raw video title string from YouTube. This produced several problems:
1. YouTube creators frequently use fancy Unicode mathematical fonts (such as `《 เพลงรัก 》𝗯𝘆 𝗟𝗶𝘇'ｓ x 𝐍𝐀𝐓𝐍𝐎𝐍`), which produced awkward filenames, broke search indexing, and failed on standard terminal/file viewers.
2. Official YouTube Music tracks provide separate `artist` and `track` tags, but the system previously ignored the `artist` field entirely and only used the song name.
3. User-uploaded songs often lacked the `artist` tag (`None`), yet the uploader or channel (e.g. `Liz's | WISLIVE`) or the title itself (`Song by Artist`) contained the artist identity.
4. Naive string concatenation of channel and title caused duplicates for titles that already had `Artist - Song` (e.g. `NONT TANONT - โต๊ะริม - LOVEiS`).

**Considered Options:**
- Keep title only — rejected: Users want to know both the artist and the song when generating covers and viewing their library.
- Format as `[Song] - [Artist]` — rejected: Standard audio library convention and Windows file organization prefers `[Artist] - [Song]` (e.g. `Liz's x NATNON - เพลงรัก (Model Ver).mp3`).
- Multi-tier `extract_song_and_artist()` with NFKC Normalization — accepted:
  1. Apply `unicodedata.normalize('NFKC', ...)` to convert mathematical alphanumeric characters to standard ASCII/Unicode letters and strip decorative brackets (`《 》`, `【 】`).
  2. If `track` and `artist` metadata exist (Official YouTube Music releases), format directly as `{artist} - {track}`.
  3. If title matches `Song by Artist` or `Song โดย Artist`, parse and rearrange into `{artist} - {song}`.
  4. If title already has ` - `, clean promotional noise and keep the pre-formatted title.
  5. Otherwise, fallback to the cleaned channel/uploader name as the artist if it is not already a substring in the title.
  6. Clean promotional channel noise (`- Topic`, `Official`, `| Agency`, `VEVO`).

**Consequences:**
- Output audio files now clearly identify both the original artist and song name (e.g. `Liz's x NATNON - เพลงรัก (Model Ver).mp3`).
- YouTube fancy fonts are cleanly normalized to readable text.
- Full backwards compatibility with all existing cover generation pipelines and UI components.
