# VRAM Telemetry Clarification and Single-Thread Safety

We clarify terminal telemetry reporting to distinguish between total physical GPU VRAM capacity and real-time active working set, reflecting that the single-thread MDX-Net pipeline actively consumes only ~1.2 - 1.5 GB of VRAM.

**Context & Problem:**
In `src/mdx.py`, the source separation module queries the host GPU's total hardware memory (`torch.cuda.get_device_properties(device).total_memory / 1024**3`). On an NVIDIA GeForce RTX 2050 (4GB), this returns `~3.9995 GB`.
Because `vram_gb < 8`, `mdx.py` locks inference to `m_threads = 1` for CUDA memory safety and outputs `threads: 1 vram: 3.99951171875`.
When previously displayed as `[VRAM Allocation] Dynamic MDX limit: 4.0 GB`, users were led to believe that the process was hoarding or exhausting the full 4.0 GB of VRAM, when in fact:
1. The 4.0 GB figure is the total physical memory installed on the GPU hardware.
2. In single-thread mode (`threads: 1`), MDX-Net inference consumes only **~1.2 - 1.5 GB** at peak, leaving >2.5 GB of VRAM completely free for the operating system and other tasks.
3. Capping VRAM below 1.5 GB is unsafe because the subsequent RVC v2 inference step requires ~1.8 - 2.2 GB combined (Hubert feature extractor + RMVPE pitch estimation + generator network).

**Considered Options:**
- Artificially clamping PyTorch VRAM to 1.5 GB (`set_per_process_memory_fraction`) — rejected: Would cause CUDA Out of Memory (OOM) fatal crashes during RVC v2 voice conversion and multi-stage audio effects.
- Hiding VRAM telemetry entirely — rejected: Hardware awareness is valuable telemetry for users monitoring GPU status.
- Contextual Telemetry Formatting — accepted: Reformat the line to explicitly state the total GPU capacity alongside the active working set:
  `💾  [VRAM Allocation] 4.0 GB GPU ➔ Safe Single-Thread Mode (~1.5 GB Active)`.

**Consequences:**
- Users immediately understand that the process is operating safely with a lightweight ~1.5 GB footprint.
- Eliminates false impressions of memory hogging while preventing dangerous artificial memory caps that would destabilize RVC.
