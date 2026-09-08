# Unicode-Safe In-Memory FAISS Index Deserialization

We implement an in-memory binary fallback (`faiss.deserialize_index`) for loading FAISS feature retrieval index files (`.index`) to guarantee 100% compatibility with Unicode and Thai model folder paths on Windows.

**Context & Problem:**
When voice models are organized into folders with Thai or non-ASCII characters (e.g. `rvc_models\โต ซิลลี่ฟูลส์\` or `rvc_models\จ๋าย ไททศมิตร\`), calling `faiss.read_index(file_index)` in `src/vc_infer_pipeline.py` crashes with:
`RuntimeError: Error in __cdecl faiss::FileIOReader::FileIOReader(const char *) ... Error: 'f' failed: could not open ... for reading: No such file or directory`

This occurs because FAISS's underlying C++ `FileIOReader` on Windows uses the C runtime `fopen(const char*, "rb")`, which interprets paths according to the system's ANSI code page (ACP) rather than UTF-8. When `fopen` fails, the exception was caught and logged via `traceback.print_exc()`, triggering the terminal's Cyberpunk Error Diagnostic Card and silently disabling index retrieval (`index_rate = 0`), which severely degrades voice conversion timbre fidelity.

**Considered Options:**
- Forcing users to rename model directories to English/ASCII — rejected: Degrades user experience for Thai users who expect native Thai model names to work out of the box.
- Temporary file copying to ASCII paths — rejected: Requires disk I/O, temporary directory cleanup, and adds overhead for multi-megabyte index files.
- In-Memory Deserialization Fallback — accepted:
  1. Attempt `faiss.read_index(file_index)` for standard ASCII paths.
  2. Upon any exception (or non-ASCII path), open the file via Python's native `open(file_index, 'rb')` (which supports full Unicode on Windows via `_wfopen`).
  3. Load the binary data into a numpy uint8 buffer and deserialize directly into FAISS via `faiss.deserialize_index(np.frombuffer(data, dtype=np.uint8))`.

**Consequences:**
- Zero errors or diagnostic card alerts when selecting Thai voice models (`โต ซิลลี่ฟูลส์`, `จ๋าย ไททศมิตร`, etc.).
- The RVC pipeline correctly utilizes the `.index` feature embeddings (`reconstruct_n`), producing pristine vocal conversion quality without fallback degradation.
- Zero disk overhead; deserialization occurs entirely in memory in milliseconds.
