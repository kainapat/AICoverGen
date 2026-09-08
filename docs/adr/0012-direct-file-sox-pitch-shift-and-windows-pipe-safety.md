# Direct File SoX Pitch Shifting and Windows Pipe Safety

We replace piped array streaming (`tfm.build_array`) with direct file transformation (`tfm.build_file`) in `pitch_shift()`, eliminating Windows CRT standard output pipe byte-misalignment exceptions when applying overall pitch changes (`pitch_change_all`).

**Context & Problem:**
When users specify an overall pitch adjustment (`pitch_change_all != 0`), the pipeline executes `pitch_shift()` on both `instrumentals_path` and `backup_vocals_path`.
Previously, `pitch_shift()` read the audio file into memory via `soundfile.read()`, fed it to `sox.Transformer.build_array()`, and serialized the output back to disk.
On Windows, `sox.Transformer.build_array()` runs `sox.exe` and reads raw PCM bytes through a standard stdout pipe (`process_handle.communicate()`). Due to Windows CRT text-mode CRLF transformations (`0x0A` expanding to `0x0D 0x0A`) or process buffer flush boundaries on pipe closure, the returned byte count frequently diverges from a multiple of the data type size (e.g. `44855986` bytes instead of a multiple of 8 for float64).
This triggered:
`ValueError: buffer size must be a multiple of element size` in `numpy.frombuffer()`, crashing the pipeline during `[~] Applying overall pitch change`.

**Considered Options:**
- Post-truncating array bytes (`out[:len(out) - len(out) % element_size]`) — rejected: Leaves pipe overhead in place and modifies third-party package internals (`site-packages/sox/transform.py`).
- External subprocess calls to ffmpeg — rejected: Introduces new dependency configurations and potential sample-rate mismatch.
- Direct File Transformation (`tfm.build_file`) with fallback — accepted:
  1. Call `tfm.build_file(input_filepath=audio_path, output_filepath=output_path)` directly.
  2. SoX processes the audio file directly on disk, writing exact WAV container headers and PCM frame boundaries without passing raw bytes across Windows standard output pipes.
  3. Keep `build_array` as a fallback in case of exceptional file access errors.

**Consequences:**
- Overall pitch shifting (`pitch_change_all`) works reliably on both vocal stems and instrumental tracks of any duration or channel count.
- Avoids memory duplication from loading multi-megabyte numpy arrays in Python before and after SoX processing.
- Zero pipe-related byte truncation or `ValueError` crashes on Windows.
