# Two-Tier Naming Architecture for Windows RVC

We decouple internal working directories and intermediate audio file naming from the final human-readable cover output filename. 
Internal pipeline stages use ASCII-safe song IDs (YouTube video ID or hash) to satisfy Windows libsndfile/RVC constraints, while the final export layer formats the output file as `<Song Title> (<Voice Model> Ver).<ext>` with user-editable and auto-sanitized song title metadata.

**Context & Problem:**
On Windows, `libsndfile` and native C-extensions in RVC crash or fail silently when encountering non-ASCII characters (such as Thai, Japanese, Chinese, or emoji) in file paths. In contrast, users expect human-readable filenames for generated songs instead of cryptic 11-character YouTube video IDs. Furthermore, when downloading YouTube tracks in the WebUI, the original video title was previously lost because the downloaded file was named after the video ID and treated as a local audio path.

**Considered Options:**
- Single-tier Unicode naming throughout the entire pipeline — rejected: crashes libsndfile and RVC on Windows.
- Keep video ID / hash everywhere — rejected: terrible user experience; users cannot identify songs in their audio library.
- Two-tier naming (ASCII-safe internal staging + metadata threading to final export) — accepted: provides complete stability on Windows while delivering the desired `<Song Title> (<Voice Model> Ver).mp3` output naming.

**Consequences:**
The WebUI exposes an editable `Song Title` field that auto-populates upon URL processing or local upload. The pipeline threads `song_title` to `process_song` and `combine_audio`, writing the final output with UTF-8/Unicode filename support via ffmpeg/pydub while maintaining ASCII-safe paths for all intermediate MDX and RVC steps.
