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
| **Smart Launcher** | `run_aicovergen.bat` — kills orphaned processes, checks port, launches WebUI with logging, verifies startup. |

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
