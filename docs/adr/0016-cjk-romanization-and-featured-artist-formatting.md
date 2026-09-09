# CJK Romanization and Featured Artist Formatting

We standardize Japanese and Korean song titles by automatically appending Title-Cased Romaji in parentheses and repositioning featured artists to the end of the title layout as `[Main Artist] - [Song Title (Romaji)] Feat. [Featured Artist]`.

**Context & Problem:**
Previously, when downloading Japanese or Korean songs from YouTube or YouTube Music:
1. Non-CJK users could not read or pronounce original Kanji, Hiragana, Katakana, or Hangul titles (e.g. `藍より群青` or `밤양갱`).
2. Songs featuring other artists frequently had messy metadata: YouTube Music provided `artist: "Takaaki Natsushiro, Suisei Hoshimachi"` and `track: "藍より群青 (feat. 星街すいせい)"`, resulting in redundant filenames like `Takaaki Natsushiro, Suisei Hoshimachi - 藍より群青 (feat. 星街すいせい)`.
3. The inline `(feat. ...)` tag cluttered the core song title and prevented clean sorting in library and cover outputs.

**Considered Options:**
- Replace CJK characters completely with Romaji — rejected: Preserving original script maintains cultural fidelity, authentic search matching, and avoids loss of Kanji meaning.
- Place Romaji after Feat clause (`[Artist] - [Song] Feat. [Artist] ([Romaji])`) — rejected: Romaji is the pronunciation of the song title, so it belongs immediately adjacent to the song title.
- Treat every comma in `artists` as a `Feat.` — rejected: Collabs, duos, and bands (e.g. `LiSA, Uru` or `Yoasobi`) would be incorrectly converted into features. Feature formatting should only trigger when `feat.`, `ft.`, or `featuring` is present.
- Dual CJK + Romaji title representation with parsed Feat clause — accepted:
  1. Detect Japanese (`\u3040-\u309f`, `\u30a0-\u30ff`, `\u4e00-\u9fff`) via `pykakasi` and Korean (`\uac00-\ud7a3`) via `kroman`.
  2. Append Title-Cased Romaji / Romaja in parentheses: `[Song] ([Romaji])` (e.g. `藍より群青 (Ai Yori Gunjou)`).
  3. Strip `[\(\[\{]?(?:feat\.?|ft\.?|featuring)\s+(...)[\)\]\}]?` from the song title.
  4. Resolve featured artist name, preferring official international/romanized metadata (`artists[1:]`) or romanizing pure CJK text.
  5. Format output cleanly as: `[Main Artist] - [Song Title (Romaji)] Feat. [Featured Artist]`.
  6. Thai, English, and Romanized songs remain 100% untouched.

**Consequences:**
- Output filenames and WebUI displays are legible and consistent (e.g. `Takaaki Natsushiro - 藍より群青 (Ai Yori Gunjou) Feat. Suisei Hoshimachi (Model Ver).mp3`).
- Audio player cards and download cards clearly distinguish the primary vocalist, the song, its pronunciation, and featured guests.
- Completely backwards-compatible with standard single-artist and non-CJK music.
