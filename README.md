---
title: AICoverGen
emoji: 🚀
colorFrom: red
colorTo: pink
sdk: gradio
sdk_version: 5.44.0
app_file: app.py
pinned: false
license: mit
---

<div align="center">

# 🎤 AICoverGen

**สร้าง AI Song Cover ด้วยเสียงใครก็ได้ — Create AI-powered song covers with any voice**

[![Python](https://img.shields.io/badge/Python-3.10-blue?style=flat-square&logo=python)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.5.1+cu121-red?style=flat-square&logo=pytorch)](https://pytorch.org/)
[![CUDA](https://img.shields.io/badge/CUDA-12.1-green?style=flat-square&logo=nvidia)](https://developer.nvidia.com/cuda-toolkit)
[![Gradio](https://img.shields.io/badge/Gradio-5.44-orange?style=flat-square&logo=gradio)](https://gradio.app/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Models](https://img.shields.io/badge/Voice_Models-59-purple?style=flat-square)](rvc_models/public_models.json)

[🚀 Online Demo](https://huggingface.co/spaces/r3gm/AICoverGen) · [📙 Colab](https://colab.research.google.com/github/R3gm/AICoverGen/blob/main/colab_notebook.ipynb) · [🐛 Troubleshooting](TROUBLESHOOTING.md)

</div>

---

## ✨ Features | ฟีเจอร์

| 🎯 | EN | TH |
|----|----|----|
| 🎙️ **Voice Models** | 59+ public models, one-click download | โมเดลเสียง 59+ ตัว โหลดได้ในคลิกเดียว |
| 🔗 **YouTube Input** | Standard, Shorts, Embed, Playlist, YouTube Music | รองรับลิงก์ทุกรูปแบบ + YouTube Music |
| 🎚️ **Pitch Control** | Vocals-only (gender convert) + overall key shift | ปรับ pitch เสียงร้อง / ทั้งเพลง |
| 🎛️ **Audio Mixing** | Reverb, chorus, delay, compressor, gain | เอฟเฟกต์ครบ: reverb, chorus, delay, compressor |
| 🌐 **Bilingual UI** | Thai 🇹🇭 / English 🇬🇧 interface | หน้าจอ 2 ภาษา ไทย–อังกฤษ |
| ⚡ **Low-VRAM Ready** | Auto-optimizes for 4GB GPUs (FP16, reduced padding) | ใช้ได้แม้การ์ดจอ VRAM 4GB |
| 📊 **Live Progress** | Per-stage timing in terminal + WebUI log | เห็นเวลาทำงานแต่ละขั้นตอนแบบ real-time |

---

## 📸 Screenshots | ภาพตัวอย่าง

<div align="center">

### Generate Tab | หน้าสร้างเพลง
![Generate](images/webui_generate.png)

### Download Model Tab | หน้าโหลดโมเดล
![Download Model](images/webui_dl_model.png)

### Upload Model Tab | หน้าอัปโหลดโมเดล
![Upload Model](images/webui_upload_model.png)

</div>

---

## 🚀 Quick Start | เริ่มใช้งาน (Windows)

### 1️⃣ Double-click — ง่ายที่สุด

```
run_aicovergen.bat
```

Smart launcher: ฆ่า process เก่า → เช็ค Python → รัน WebUI → เปิด `http://127.0.0.1:7860`

### 2️⃣ Alternatives | วิธีอื่น

| Method | Command |
|--------|---------|
| 🪟 PowerShell | `python launch.py` |
| ⌨️ Classic CMD | `start_simple.bat` |
| 🔧 Manual | `.\.venv\Scripts\python.exe src\webui.py --listen --listen-port 7860` |
| ▶️ Built-in player | เพิ่ม `--builtin-player` เพื่อฟังผลลัพธ์ใน WebUI โดยตรง |

> 🛑 **หยุดโปรแกรม:** กด `Ctrl+C` ในหน้าต่าง terminal (ฆ่าทั้ง process tree อัตโนมัติ)

---

## 🎵 How to Use | วิธีใช้งาน

```
1. 📥 Download model tab  →  เลือกเสียงจาก Public Models (เช่น Ado, YOASOBI, KOBASOLO)
2. 🎼 Generate tab         →  วาง YouTube URL หรืออัปโหลดไฟล์เสียง
3. 🎚️ ตั้ง Pitch            →  +1/-1 สำหรับแปลงเพศเสียง
4. ▶️ กด Generate!          →  รอ + ดาวน์โหลดเพลงที่ได้
```

### ⏱️ Terminal Output | ตัวอย่างผลลัพธ์

```
[18:15:02] [~] Starting AI Cover Generation Pipeline...
[18:15:05] [~] Downloading song... [+3s]
[18:15:20] [~] Separating Vocals from Instrumental... [+15s]
[18:17:45] [~] Separating Main Vocals from Backup Vocals... [+2m 25s]
[18:19:30] [~] Converting voice using RVC... [+1m 20s]
[+] Total time all process: 7m 8s (428.1s)
```

`[+Xs]` = เวลาที่ใช้ในแต่ละขั้นตอน · `[+] Total time` = เวลารวมทั้งหมด

---

## 💻 Requirements | สิ่งที่ต้องมี

| | |
|--|--|
| 🐍 Python | **3.10** (torch ไม่รองรับ 3.14) — ใช้ `.venv` ที่เตรียมไว้ |
| 🎮 GPU | NVIDIA + CUDA (ทดสอบบน **RTX 2050 4GB** ✅) |
| 💾 Disk | ~2GB (models) + พื้นที่ไฟล์เพลง |
| 🎵 FFmpeg | มาพร้อม imageio-ffmpeg อัตโนมัติ |

### ⚡ RTX 2050 4GB Optimization

ไม่ต้องแก้โค้ด — โปรแกรมปรับให้อัตโนมัติตาม VRAM:

- ✅ Half precision (FP16) บน CUDA — ใช้ VRAM ครึ่งเดียว
- ✅ MDX ใช้ 1 thread เมื่อ VRAM < 8GB (`mdx.py`)
- ✅ RVC ลด padding เมื่อ VRAM ≤ 4GB (`rvc.py`: `x_pad=1, x_query=5, x_center=30, x_max=32`)

---

## 🎙️ Voice Models | โมเดลเสียง

- 📁 โมเดลเก็บใน `rvc_models/` — กด **Refresh Models 🔁** หลังเพิ่มไฟล์ใหม่
- 🌐 **59 public models** ใน [`public_models.json`](rvc_models/public_models.json) — โหลดจากแท็บ Download ได้เลย
- ⭐ ล่าสุด: **Ado**, **KOBASOLO**, **YOASOBI** (RVC V2)
- 📤 มีไฟล์ `.pth` + `.index` ของตัวเอง? วางลง `rvc_models/<ชื่อ>/` ได้ทันที

---

## 📂 Project Structure | โครงสร้างโปรเจกต์

```
AICoverGen/
├── 🚀 run_aicovergen.bat   # Smart launcher (ดับเบิลคลิก)
├── 🐍 launch.py            # Python launcher + live progress + ANSI detect
├── ⌨️ start_simple.bat     # Simple launcher (classic CMD)
├── 📖 TROUBLESHOOTING.md   # คู่มือแก้ปัญหา
├── 📘 CONTEXT.md           # Domain glossary
├── src/
│   ├── 🖥️ webui.py         # Gradio WebUI (TH/EN)
│   ├── ⚙️ main.py           # Cover pipeline + timing
│   ├── 🎤 mdx.py            # Vocal separation (MDX)
│   ├── 🗣️ rvc.py            # Voice conversion (RVC)
│   └── ⬇️ download_models.py # Model downloader
├── 🎙️ rvc_models/          # Voice models + public_models.json
├── 🎼 mdxnet_models/       # MDX separation models (ONNX)
└── 🎵 song_output/         # ผลลัพธ์เพลงที่สร้าง
```

---

## 🆘 Troubleshooting | แก้ปัญหา

เจอ error? เปิด [**TROUBLESHOOTING.md**](TROUBLESHOOTING.md) — รวมวิธีแก้:

- 🔌 Port 7860 ถูกใช้อยู่ → launcher ฆ่าให้อัตโนมัติ
- 📦 MDX model hash ไม่ตรง → ลบไฟล์ + รัน `download_models.py` ใหม่
- 🔤 ชื่อไฟล์ภาษาไทย error → ใช้ชื่อ video ID อัตโนมัติแล้ว
- ⬇️ HuggingFace gated repo (401/403) → ใช้ public mirror แทน

---

## 🙏 Credits | ที่มา

> 👉 Fork ของ [R3gm/AICoverGen](https://github.com/R3gm/AICoverGen) (ต้นฉบับจาก [SociallyIneptWeeb/AICoverGen](https://github.com/SociallyIneptWeeb/AICoverGen)) — ปรับปรุงเพิ่ม: Smart launcher, bilingual UI, live progress timing, public model index, TROUBLESHOOTING guide, low-VRAM optimization docs
>
> 🎤 Voice models: ดู credit ใน [`public_models.json`](rvc_models/public_models.json) · 🙏 ขอบคุณเจ้าของโมเดลทุกท่าน
