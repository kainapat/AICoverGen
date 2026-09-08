# Dedicated Downloads Folder and WebUI Cache Cleanup

We isolate all audio downloads from YouTube and YouTube Music into a dedicated `downloads/` directory and provide a WebUI action (`🗑️ ล้างดาวน์โหลด / Clear`) to purge cached source files without affecting final song covers.

**Context & Problem:**
Previously, `yt_download()` in `src/main.py` specified `'outtmpl': '%(id)s'` without a target directory path. Because `run_aicovergen.bat` executes from the project root (`d:\Code\AICoverGen`), `yt-dlp` deposited all downloaded `.mp3` files and sidecar `.title` metadata directly into the workspace root.
Over time, dozens of audio files (e.g. 89 files) accumulated in the project root alongside source files, confusing navigation, increasing backup overhead, and cluttering directory listings. Furthermore, users had no in-app way to reclaim disk space after processing songs.

**Considered Options:**
- Keep storing in project root and rely on manual file explorer deletion — rejected: Clutters workspace and causes confusion with project source files.
- Store inside per-song working folders (`song_output/<song_id>/`) — rejected: Prevents reusing downloaded files across different RVC voice models or different inference runs without redownloading.
- Dedicated `downloads/` folder with WebUI cleanup button — accepted:
  1. Define `downloads_dir = os.path.join(BASE_DIR, 'downloads')` in `src/main.py` and `src/webui.py`.
  2. Configure `yt_download()` to output directly to `downloads_dir`.
  3. Migrate all existing `.mp3` and `.title` files from root into `downloads/`.
  4. Add a `🗑️ ล้างดาวน์โหลด / Clear` button on the WebUI alongside `โหลด URL / Process URL` calling `clear_downloads_action()`, which purges staging files from `downloads/` while leaving generated song covers in `song_output/` intact.

**Consequences:**
- Project root directory remains completely clean and dedicated to source code and configuration.
- Downloaded audio files are neatly organized in `downloads/` and already ignored by Git via `.gitignore`.
- Users can clear cached audio files on demand with a single click in the WebUI.
- Generated song covers in `song_output/` remain safe and unaffected during downloads cache cleanup.
