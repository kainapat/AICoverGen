# Inline Audio Streaming and UTF-8 Content-Disposition

We patch Gradio's MIME type classification and attach custom FastAPI response headers in `src/webui.py`, ensuring audio responses are served with `Content-Disposition: inline` and proper MIME types (`audio/mpeg`, `audio/wav`), preventing external download managers from hijacking in-browser playback and preserving Unicode Thai characters in downloaded filenames.

**Context & Problem:**
On Windows systems, Python's `mimetypes.guess_type()` classifies `.mp3` files as `audio/mp3` instead of `audio/mpeg`. Because `audio/mp3` is absent from Gradio's internal `XSS_SAFE_MIMETYPES` whitelist, Gradio automatically downgrades the served file to `application/octet-stream` and attaches `Content-Disposition: attachment`. This causes two critical failures:
1. Web browsers refuse to stream the audio within the native `<audio>` player element and instead attempt a forced file download. External download interceptors (such as Internet Download Manager / IDM) hook this network request, preventing users from playing audio in the WebUI.
2. When IDM intercepts the download, its legacy filename sanitizer strips non-spacing combining characters (Unicode Category `Mn`), causing all Thai vowels and tone marks (e.g. `ั`, `้`, `ุ`) and parentheses to be deleted from the filename (e.g. `ฉบับท้ายสุด` becomes `ฉบบทายสด`).

**Considered Options:**
- Rely solely on user configuration in IDM — rejected: users should not have to manually reconfigure external software to use basic WebUI player features.
- Patch only `mimetypes` — partially accepted: solves MIME guessing but does not protect against Gradio cache folder path edge cases where files are marked as `reason == "created"`.
- Two-Tier Header Defense: Patch `XSS_SAFE_MIMETYPES` + register `audio/mpeg` + apply FastAPI response middleware — accepted: guarantees `Content-Disposition: inline` and RFC 5987 UTF-8 `filename*` headers for all audio files served through Gradio.

**Consequences:**
The in-browser `<audio>` player natively streams MP3 and WAV outputs without triggering forced download dialogs. Download managers do not hijack internal player streaming on localhost. Explicit UTF-8 filename headers ensure downloaded files retain all Thai vowels, tone marks, and special characters intact.
