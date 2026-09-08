# Context — AICoverGen (Local Instance)

## Glossary

| Term | Definition |
|---|---|
| **RVC** | Retrieval-based Voice Conversion — deep learning model that converts one voice to sound like another while preserving the original performance's pitch and timing. |
| **MDX** | Music Source Separation — ONNX-based neural network that separates audio into stems (vocals, instrumentals, drums, bass). |
| **Hubert** | Self-supervised speech representation model used as feature extractor for RVC. Loaded once at startup, stays in VRAM. |
| **RMVPE** | Robust Model for Vocal Pitch Estimation — pitch detection algorithm; default `f0_method` for voice conversion. |
| **Crepe** | Alternative pitch detection algorithm; `mangio-crepe` variant with configurable `crepe_hop_length`. |
| **Voice Model (.pth)** | Pre-trained RVC checkpoint file containing the target voice's learned parameters. |
| **Index File (.index)** | Optional FAISS index for timbre leakage reduction; improves voice similarity when paired with a .pth model. |
| **Vocal Separation** | Splitting a song into isolated vocals and instrumentals using MDX ONNX models. |
| **DeReverb** | Post-processing step that removes reverb artifacts from isolated vocals. |
| **Half Precision (FP16)** | Using 16-bit floats instead of 32-bit for GPU inference — halves VRAM usage with minimal quality loss on CUDA GPUs. |
| **VRAM** | Video RAM on the GPU; RTX 2050 has ~4GB. Critical bottleneck for this pipeline. |
| **Song Cover Pipeline** | Full workflow: download → separate vocals → extract main vocals → deReverb → RVC voice change → audio effects → combine → output. |
| **WebUI** | Gradio-based web interface (`src/webui.py`) providing GUI for the cover pipeline. Runs on port 7860. |
| **Spaces** | HuggingFace ZeroGPU decorator (`@spaces.GPU`); no-op when `SPACES_ZERO_GPU` env var is unset (local runs). |
| **Pitch Change** | Transposition applied to AI vocals only. `+1` = male→female, `-1` = female→male. In semitones × 12. |
| **Pitch Change All** | Transposition applied to both vocals AND instrumentals (slightly reduces quality). |
| **Index Rate** | 0.0–1.0 controlling timbre leakage; higher = more influenced by training dataset quality. |
| **Filter Radius** | 0–7 median filter on pitch results; ≥3 reduces breathiness. |
| **RMS Mix Rate** | 0.0 = original vocal loudness, 1.0 = fixed loudness. Controls vocal dynamics preservation. |
| **Protect** | 0.0–0.5 protecting voiceless consonants from artifacts; 0.5 = disabled. |
| **Pedalboard** | Spotify's audio effects library; applies HighpassFilter, Compressor, Reverb to converted vocals. |
| **NoiseReduce** | Optional denoising pass (`noisereduce` library) applied before audio effects. |
| **Total time all process** | Terminal line printed at pipeline end showing full duration from start to finish (e.g. `[+] Total time all process: 7m 8s (428.1s)`). |
| **Stage timing** | `[+Xs]` / `[+Xm XXs]` suffix on each progress line showing time spent since the previous pipeline stage. |
| **Smart Launcher** | `run_aicovergen.bat` — kills orphaned processes, checks port, launches WebUI with logging, verifies startup. |
| **Song Title** | Clean, human-readable title of the song (e.g. `สุดใจ`, `Pretender`) with promotional noise removed. Used for UI display and final file naming. |
| **Cover Filename** | The human-readable output audio file formatted as `<Song Title> (<Voice Model> Ver).<ext>` (e.g. `สุดใจ (NontTanont Ver).mp3`). |
| **Song ID / Video ID** | 11-character YouTube video ID or hash used for internal working directories (`song_output/<song_id>`) to guarantee ASCII-safe intermediate file paths on Windows. |
| **Clean Title Filter** | Regex post-processing on YouTube metadata stripping noise tags such as `[Official MV]`, `(Official Audio)`, `【MV】`, `4K`, `HD`. |
| **Dual Output Display** | Pairing an in-browser audio player (`gr.Audio`) for instantaneous playback with a dedicated file card (`gr.File`) for direct download in the WebUI. |
| **Cyberpunk Launcher CLI** | High-aesthetic terminal interface with rounded Unicode boxes, ANSI gradients, live GPU/VRAM hardware telemetry, and formatted pipeline stage streaming. |
| **Fast Mode** | Pipeline optimization flag (`fast_mode=True`) bypassing redundant multi-pass ONNX denoising, reducing separation duration by ~50% (~2-3 mins on 4GB VRAM) while preserving vocal clarity. |
| **Error Diagnostic Card** | Cyberpunk-styled terminal alert box rendering exception classes, source locations, and human-readable remedies when errors occur. |
| **Traceback Buffer Drainer** | Pipe management pattern in `launch.py` ensuring stdout/stderr buffers are fully drained on process crash so stacktraces are never truncated. |
| **Atomic Chunk Counter** | Thread-safe in-memory progress counter in `src/mdx.py` replacing disabled `tqdm` to guarantee accurate chunk tracking (`X/Y chunks`) and realistic ETA calculations. |
| **UTF-8 Pipe & Console Enforcement** | Explicit UTF-8 subprocess environment (`PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`) and stream reconfig preventing Windows code page Mojibake (`â–‘â–‘`). |
| **Inline Audio Streaming** | Server-side MIME & header patch ensuring `Content-Disposition: inline` and `audio/mpeg` for `.mp3` files, enabling native in-browser playback without download manager interception. |
| **RFC 5987 Filename Encoding** | Standardized `filename*=utf-8''` HTTP header encoding preserving Unicode characters (Thai vowels, tone marks, diacritics) across browser file downloads. |
| **Cyberpunk Audio Player Card** | Unified HTML5 audio player and download card using in-memory Data URIs (`data:audio/mpeg;base64,...`) to completely isolate playback from external download managers (IDM), preventing unwanted auto-downloads and preserving full Thai diacritics. |
| **Windows Asyncio Disconnect Suppressor** | Patch and log filter catching benign TCP resets (`WinError 10054` in `_ProactorBasePipeTransport`) caused by client page refreshes or tab closures, preventing false-positive error diagnostic cards. |
| **Custom Cyberpunk Audio Controller** | Fully custom-styled media player bar replacing browser-native audio controls with a dark-glass container, neon cyan controls, monospace time display, volume slider, and real-time seek timeline. |
| **Permanent Scrubber Visibility** | Continuous 100% visibility of the timeline thumb circle (`::-webkit-slider-thumb`) and progress gradient without requiring mouse hover, overcoming Chromium's native Shadow DOM auto-hide behavior. |
| **Cyberpunk Terminal Sub-steps** | Formatted secondary stdout/stderr stream lines indented with icons and colors (ASCII routing, ONNX provider, RVC keys match, speed multiplier, noise reduction) maintaining clean visual hierarchy. |
| **Runtime Notice Banner** | Formatted Amber notification (`⚠️  [RUNTIME NOTICE]`) contextualizing library deprecation warnings (e.g. yt-dlp Python 3.10 EOL) and confirming standard engine compatibility. |

## Pipeline Flow

```
YouTube URL / Local Audio
    ↓
yt_download (yt_dlp) → MP3
    ↓
MDX Vocals+Instrumental separation (UVR-MDX-NET-Voc_FT.onnx)
    ↓
MDX Main+Backup vocals separation (UVR_MDXNET_KARA_2.onnx)
    ↓
MDX DeReverb (Reverb_HQ_By_FoxJoy.onnx)
    ↓
RVC Voice Conversion (voice model .pth + index .index)
    ↓
Audio Effects (Pedalboard: HPF + Compressor + Reverb)
    ↓
Optional: NoiseReduce
    ↓
MDX Voiceless extraction (UVR-MDX-NET-Inst_HQ_4.onnx)
    ↓
Optional: Pitch Shift (SoX)
    ↓
Combine (pydub: main + backup + instrumental)
    ↓
Output (.mp3 or .wav)
```

## Key Constraints

| Constraint | Value | Impact |
|---|---|---|
| GPU | RTX 2050, 4GB VRAM | Half precision mandatory; MDX 1 thread; RVC reduced padding |
| Python | 3.10.11 | torch 2.5.1+cu124 requires ≤3.12 |
| Disk Free | C: 36.5GB, D: 168.9GB | song_output grows with keep_files |
| WebUI | Gradio 5.44.0 | Blocks terminal when running |
| Fairseq | Built from source | Only works with Python 3.10 on Windows |
