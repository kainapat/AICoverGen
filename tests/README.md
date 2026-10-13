# วิธีรันทดสอบ | Test Guide

## 1. Unit Tests (system Python — ไม่ต้องใช้ GPU/โมเดล)

```powershell
python -m pytest tests/test_lyrics.py tests/test_lyrics_phase2.py tests/test_lyrics_alignment_guard.py tests/test_review.py tests/test_eval.py tests/test_webui_wiring.py
```

`test_webui_wiring.py` ตรวจโครง UI ผ่าน AST (ไม่ต้อง import gradio/torch): handler ทุกปุ่มต้องมีตัวตน, arity ของ inputs/outputs ต้องตรง, `run_cover_webui` ต้องคืน VRAM (`free_lyrics_models`) ก่อนเรียก pipeline

`test_e2e_lyrics.py` จะ skip เคสที่ต้องใช้ไฟล์เสียงจริง/soundfile บน system Python โดยอัตโนมัติ

## 2. Integration + Real Audio Tests (ต้องใช้ `.venv`)

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review tests.test_postrvc tests.test_eval tests.test_e2e_lyrics tests.test_clean_song_title tests.test_song_metadata
```

- ต้องมี `song_output/0c1231cc669/*.wav` (เสียงร้องแยกแล้ว) สำหรับเคสเสียงจริง — ถ้าไม่มีจะ skip พร้อมเหตุผล ไม่ fail
- เคสเสียงจริงใช้โมเดล `tiny` บน CPU เป็นหลัก (กัน VRAM ชนกับ RVC) ยกเว้นเคสวัด CUDA ที่ guard ด้วย try/except
- ห้ามอ้างความแม่นยำของ ASR: tests ไม่มี ground-truth lyrics ตรวจแค่โครงสร้าง (types, hash, timeline, ไม่เขียนทับไฟล์)

## 3. ข้อจำกัดที่รู้แล้ว

- Transcript อาจต่างกันเล็กน้อยระหว่างรัน (temperature fallback) — tests ห้าม assert ข้อความ ASR ตรงตัว
- TH word-level ขึ้นกับ F.1 mapping guard; ไทยส่วนใหญ่ได้ segment อย่างซื่อสัตย์
- ไม่รันสร้าง cover เต็มเพลงใน tests (ช้าหลายนาที + สร้างไฟล์ขยะ)
- VRAM: `measure_runtime` วัดเฉพาะ torch allocator — ดูทั้งการ์ดด้วย `nvidia-smi`
