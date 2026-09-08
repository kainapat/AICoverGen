# AICoverGen — Troubleshooting Guide

## WebUI ไม่เปิด (Port 7860 not listening)

### อาการ
- เข้า `http://127.0.0.1:7860` ไม่ได้ / Connection refused
- `run_aicovergen.bat` แสดง "ERROR: WebUI failed to start!"

### แก้ไข
```cmd
:: ค้นหา process ที่ใช้ port
netstat -aon | findstr ":7860" | findstr "LISTENING"

:: ฆ่า process
taskkill /F /PID <PID>

:: รัน batch file ใหม่
run_aicovergen.bat
```

### ถ้ายังไม่ทำงาน
- ดู log: `webui.log` ในโฟลเดอร์ `D:\Code\AICoverGen\`
- ตรวจสอบว่า `.venv` ใช้ Python 3.10.11 ไม่ใช่ 3.14

---

## CUDA Out of Memory (VRAM เต็ม)

### อาการ
- Python crash ระหว่าง `process_song` หรือ `voice_change`
- `RuntimeError: CUDA out of memory`
- `torch.cuda.OutOfMemoryError`

### แก้ไข
1. **ลด `m_threads`** ใน `mdx.py` line 255: `m_threads = 1` สำหรับ VRAM < 8GB ✅ มีอยู่แล้ว
2. **ลด `x_center`, `x_max`** ใน `rvc.py` line 101-105: มี config สำหรับ `gpu_mem <= 4` ✅
3. **ปิดโปรแกรมอื่นๆ** ที่ใช้ GPU (browser, etc.)
4. **ลดความยาวเพลง** — เพลงที่ยาวกว่าต้องการ VRAM มากกว่า
5. **Restart WebUI** — ฆ่า process แล้วเปิดใหม่เพื่อเคลียร์ VRAM

### ถ้ายังไม่ทำงาน
- ตรวจสอบ VRAM: `D:\Code\AICoverGen\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.memory_allocated(0)/1024**3, 'GB used')"`
- ถ้า VRAM เต็มแต่ยังไม่ถึง 4GB: ลด `is_half=False` ใน `main.py` line 248 (จะใช้ memory น้อยลงแต่ช้ากว่า)

---

## Voice Model ไม่ทำงาน (.pth/.index)

### อาการ
- `Error: No model file exists in rvc_models/<voice_model>/`
- `ModuleNotFoundError: No module named 'main'` (WebUI crash)
- Voice conversion ไม่ได้ผล / เสียงเพี้ยน

### แก้ไข
1. **ตรวจสอบโฟลเดอร์**: `rvc_models/<voice_model_name>/` ต้องมี `.pth` และ `.index` file
2. **ตรวจสอบรูปแบบ**: ต้องเป็น RVC v2 format (มี `config` และ `weight` ใน .pth file)
3. **ดึง model จาก WebUI**: Public models สามารถดาวน์โหลดได้จาก `rvc_models/public_models.json` ใน WebUI
4. **ตรวจสอบ file path**: path ต้องมี space ไม่เกินไป ต้องใช้ path ที่ถูกต้อง

### ตัวอย่าง voice model folder structure
```
rvc_models/
└── MyVoice/
    ├── voice_model.pth
    └── voice_model.index
```

---

## Audio Quality ไม่ดี (เสียงเพี้ยน / มี noise)

### อาการ
- AI cover ฟังแล้วเพี้ยน/ไม่เป็นธรรมชาติ
- มีเสียง noise ใน output
- Pitch ไม่ตรง

### ปรับ parameters
| Parameter | Default | ปรับถ้า |
|---|---|---|
| `index_rate` | 0.5 | เพิ่ม (0.6-0.8) ถ้าเสียงเพี้ยน, ลด (0.3-0.4) ถ้าไม่เป็นธรรมชาติ |
| `filter_radius` | 3 | เพิ่ม (4-5) ถ้า breathiness มาก |
| `protect` | 0.33 | เพิ่ม (0.4-0.5) ถ้า consonants เพี้ยน |
| `f0_method` | rmvpe | ลอง `mangio-crepe` ถ้า rmvpe ไม่เจอ pitch |
| `crepe_hop_length` | 128 | ลด (64-96) ถ้า `mangio-crepe` ไม่แม่น |
| `rms_mix_rate` | 0.25 | เพิ่ม (0.5) ถ้าเสียงดังเกินไป |
| `pitch_change` | 0 | เปลี่ยนตามเพศ: +1 (male→female), -1 (female→male) |

---

## Fairseq / Hubert Import Error

### อาการ
- `ModuleNotFoundError: No module named 'fairseq'`
- `ImportError: ... fairseq ...`
- WebUI ไม่เริ่ม

### แก้ไข
```cmd
cd D:\Code\AICoverGen
.\.venv\Scripts\python.exe -c "from fairseq.tasks.hubert_pretraining import HubertPretrainingTask; print('fairseq OK')"
```

- ถ้า fail: `fairseq` ต้อง build จาก source (ดู `requirements.txt`)
- ตรวจสอบ Python version: ต้องเป็น 3.10.x เท่านั้น

---

## SoX / Audio Processing Error

### อาการ
- `sox.sox.error.SoXError`
- `ModuleNotFoundError: No module named 'sox'`
- Audio file ไม่ได้ผล (pitch shift ไม่ทำงาน)

### แก้ไข
```cmd
:: ตรวจสอบ SoX
sox --version

:: ถ้าไม่พบ symlink
winget install sox_ng
:: symlink ที่ C:\Users\guy26\AppData\Local\Microsoft\WinGet\Links\sox.exe -> sox_ng.exe
```

### หมายเหตุ
- `sox` Python package (`sox==1.4.1`) ทำงานกับ binary `sox` เท่านั้น
- ถ้า `sox_ng` มี CLI ต่างจาก `sox` อาจต้องแก้ `pitch_shift()` ใน `main.py` line 190-198

---

## MDX Model Not Found

### อาการ
- `FileNotFoundError` เมื่อ `run_mdx` ถูกเรียก
- `model_data.json` ไม่มี hash ตรงกัน

### แก้ไข
- ตรวจสอบว่ามี `.onnx` files ใน `mdxnet_models/`
- `model_data.json` ต้องมี hash ตรงกับ `.onnx` file ที่ดาวน์โหลด
- ดาวน์โหลด models ใหม่: `.\.venv\Scripts\python.exe src\download_models.py`

---

## Disk Space เต็ม

### อาการ
- `OSError: [Errno 28] No space left on device`
- `shutil.rmtree` ไม่ได้ผล

### แก้ไข
- `song_output/` อาจมีโฟลเดอร์เก่ามาก — `keep_files=False` จะลบอัตโนมัติ
- ตรวจสอบ: `dir /s /q D:\Code\AICoverGen\song_output\`
- ลบโฟลเดอร์เก่าด้วยตัวเอง

---

## Common Python Version Issues

### อาการ
- `torch` ไม่ import ได้
- `numpy` version conflict
- `omegaconf` metadata error

### แก้ไข
- **Python 3.14.7** เป็น version เริ่มต้น แต่ `torch 2.5.1` ไม่สนับสนุน
- ต้องใช้ **Python 3.10.11** ใน `.venv`
- ตรวจสอบ: `.\.venv\Scripts\python.exe --version`
- ถ้า .venv ผิด: ลบ `.venv` แล้วสร้างใหม่:
```cmd
rmdir /s /q .venv
D:\Path\To\Python310\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip==24.0
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
