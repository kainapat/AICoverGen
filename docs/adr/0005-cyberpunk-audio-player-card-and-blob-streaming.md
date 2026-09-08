# Cyberpunk Audio Player Card and In-Memory Data URI Streaming

We replace Gradio’s native `gr.Audio` and `gr.File` file-serving components with a unified, high-aesthetic Cyberpunk Audio Player Card (`gr.HTML`) that embeds generated audio as an in-memory Data URI (`data:audio/mpeg;base64,...`).

**Context & Problem:**
Gradio’s default `gr.Audio(type="filepath")` component serves audio by mounting a frontend `<audio>` tag that fetches the audio stream via an HTTP GET request ending in `.mp3` (`http://127.0.0.1:7860/gradio_api/file=.../song.mp3`).
When external download accelerators (such as Internet Download Manager / IDM) are active in the user's browser, IDM’s network hook intercepts all HTTP requests with `.mp3` extensions. This caused three severe issues:
1. **Unwanted Auto-Download**: The moment a cover finishes processing, IDM immediately hijacks the browser's audio preload request, popping up download windows or automatically saving the file without the user clicking download.
2. **Broken In-Browser Playback**: Because IDM aborts the browser's HTTP socket to download the file externally, the `<audio>` player receives 0 bytes, leaving the player stuck at `0:00 / 0:00` with an empty waveform.
3. **Mutilated Thai Filenames**: IDM’s internal filename sanitizer removes non-spacing combining characters (Unicode Category `Mn`), stripping all Thai vowels and tone marks (e.g. `ฉบับท้ายสุด` becomes `ฉบบทายสด`).

**Considered Options:**
- Relying on manual IDM exclusion rules (`127.0.0.1:*`) — rejected: brittle and requires every user to manually reconfigure external software.
- Custom FastAPI streaming endpoint without `.mp3` extension — partially effective, but still vulnerable to download managers that inspect `Content-Type: audio/mpeg`.
- Cyberpunk Audio Player Card via in-memory Data URI (`data:audio/mpeg;base64,...`) — accepted: eliminates HTTP requests entirely for playback. Because Data URIs live in browser memory, download managers cannot intercept the stream. HTML5 `<audio controls>` plays instantly with full controls, and the integrated download button (`<a download="...">`) saves files client-side with 100% Thai vowel and diacritic preservation.

**Consequences:**
- Zero unwanted auto-downloads upon generation completion.
- In-browser playback works 100% reliably with full seek bar, volume, and speed controls.
- Output filenames retain all Thai vowels, tone marks, and parentheses across all browsers.
