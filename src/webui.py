import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # Silence benign Windows asyncio WinError 10054 on page refresh / tab close
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        if not hasattr(_ProactorBasePipeTransport, "_orig_call_connection_lost"):
            _ProactorBasePipeTransport._orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost
            def _safe_call_connection_lost(self, exc):
                try:
                    self._orig_call_connection_lost(exc)
                except (ConnectionResetError, OSError):
                    pass
            _ProactorBasePipeTransport._call_connection_lost = _safe_call_connection_lost
    except Exception:
        pass

import mimetypes
import tempfile
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")

import gradio as gr
import gradio.routes
gradio.routes.XSS_SAFE_MIMETYPES.add("audio/mp3")
gradio.routes.XSS_SAFE_MIMETYPES.add("audio/mpeg")
gradio.routes.XSS_SAFE_MIMETYPES.add("audio/wav")
gradio.routes.XSS_SAFE_MIMETYPES.add("audio/x-wav")

import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from argparse import ArgumentParser
import spaces
import logging
def configure_logging_libs(debug=False):
    modules = [
      "numba",
      "httpx",
      "markdown_it",
      "fairseq",
      "faiss",
    ]
    try:
        for module in modules:
            logging.getLogger(module).setLevel(logging.WARNING)
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = "3" if not debug else "1"

    except Exception as error:
        pass
configure_logging_libs()

from main import song_cover_pipeline, yt_download, sanitize_filename, clean_song_title

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_ZERO_GPU = os.getenv("SPACES_ZERO_GPU")

mdxnet_models_dir = os.path.join(BASE_DIR, 'mdxnet_models')
rvc_models_dir = os.path.join(BASE_DIR, 'rvc_models')
output_dir = os.path.join(BASE_DIR, 'song_output')
downloads_dir = os.path.join(BASE_DIR, 'downloads')


def get_current_models(models_dir):
    models_list = os.listdir(models_dir)
    items_to_remove = ['hubert_base.pt', 'MODELS.txt', 'public_models.json', 'rmvpe.pt']
    return [item for item in models_list if item not in items_to_remove]


def update_models_list():
    models_l = get_current_models(rvc_models_dir)
    return gr.update(choices=models_l)


def free_lyrics_models():
    """Best-effort cleanup of GPU-cached ASR models before cover generation.

    Lyrics checking defaults to CPU, but a user may run it on CUDA; the cached
    ctranslate2 model would then contend with RVC for VRAM. This frees only
    CUDA entries (CPU models stay warm) and never raises, so cover generation
    cannot break because of cleanup.
    """
    try:
        from lyrics.asr import unload_models
        unload_models(device="cuda")
    except Exception:
        pass


def load_public_models():
    models_table = []
    for model in public_models['voice_models']:
        if not model['name'] in voice_models:
            model = [model['name'], model['description'], model['credit'], model['url'], ', '.join(model['tags'])]
            models_table.append(model)

    tags = list(public_models['tags'].keys())
    return gr.update(value=models_table), gr.update(choices=tags)


def extract_zip(extraction_folder, zip_name):
    os.makedirs(extraction_folder)
    with zipfile.ZipFile(zip_name, 'r') as zip_ref:
        zip_ref.extractall(extraction_folder)
    os.remove(zip_name)

    index_filepath, model_filepath = None, None
    for root, dirs, files in os.walk(extraction_folder):
        for name in files:
            if name.endswith('.index') and os.stat(os.path.join(root, name)).st_size > 1024 * 100:
                index_filepath = os.path.join(root, name)

            if name.endswith('.pth') and os.stat(os.path.join(root, name)).st_size > 1024 * 1024 * 40:
                model_filepath = os.path.join(root, name)

    if not model_filepath:
        raise gr.Error(f'No .pth model file was found in the extracted zip. Please check {extraction_folder}.')

    # move model and index file to extraction folder
    os.rename(model_filepath, os.path.join(extraction_folder, os.path.basename(model_filepath)))
    if index_filepath:
        os.rename(index_filepath, os.path.join(extraction_folder, os.path.basename(index_filepath)))

    # remove any unnecessary nested folders
    for filepath in os.listdir(extraction_folder):
        if os.path.isdir(os.path.join(extraction_folder, filepath)):
            shutil.rmtree(os.path.join(extraction_folder, filepath))


def yt_download_for_ui(url):
    """Wrapper: yt_download returns (path, title). Updates local_file and song_title_input."""
    path, title = yt_download(url)
    if not path:
        return None, ""
    return path, title


def clear_downloads_action():
    """Removes all downloaded files in downloads directory and resets inputs."""
    if not os.path.exists(downloads_dir):
        gr.Info("โฟลเดอร์ดาวน์โหลดว่างเปล่า / Downloads folder is empty")
        return None, ""

    count = 0
    for fname in os.listdir(downloads_dir):
        fpath = os.path.join(downloads_dir, fname)
        try:
            if os.path.isfile(fpath) or os.path.islink(fpath):
                os.remove(fpath)
                count += 1
            elif os.path.isdir(fpath):
                shutil.rmtree(fpath)
                count += 1
        except Exception as e:
            print(f"Error removing {fpath}: {e}", flush=True)

    gr.Info(f"ล้างไฟล์ดาวน์โหลดเรียบร้อยแล้ว ({count} ไฟล์) / Cleared {count} downloaded files")
    return None, ""


def download_with_auth(url, dest, hf_token=""):
    """Download a file. Adds HuggingFace auth header when a token is given (for gated repos)."""
    token = (hf_token or "").strip()
    if token and "huggingface.co" in url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    else:
        urllib.request.urlretrieve(url, dest)


def download_online_model(url, dir_name, hf_token="", progress=gr.Progress()):
    try:
        progress(0, desc=f'[~] Downloading voice model with name {dir_name}...')
        zip_name = url.split('/')[-1].split('?')[0]
        extraction_folder = os.path.join(rvc_models_dir, dir_name)
        if os.path.exists(extraction_folder):
            raise gr.Error(f'Voice model directory {dir_name} already exists! Choose a different name for your voice model.')

        if 'pixeldrain.com' in url:
            url = f'https://pixeldrain.com/api/file/{zip_name}'

        
        if "," in url:
            urls = [u.strip() for u in url.split(",") if u.strip()]
            os.makedirs(extraction_folder, exist_ok=True)
            for u in urls:
                u = u.replace("?download=true", "")
                file_name = u.split('/')[-1]
                file_path = os.path.join(extraction_folder, file_name)
                if not os.path.exists(file_path):  # avoid re-downloading
                    download_with_auth(u, file_path, hf_token)
        else:
            download_with_auth(url, zip_name, hf_token)

            progress(0.5, desc='[~] Extracting zip...')
            extract_zip(extraction_folder, zip_name)
        return f'[+] {dir_name} Model successfully downloaded!'

    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise gr.Error(
                '🔒 โมเดลนี้อยู่ใน gated repo ของ HuggingFace (ต้อง login ก่อนโหลด) / '
                'This model is in a gated HuggingFace repo. '
                'วิธีแก้ / Fix: 1) เปิดหน้าโมเดลในเบราว์เซอร์แล้วกดยอมรับเงื่อนไข / open the model page and accept its terms, '
                '2) สร้าง token ฟรีที่ huggingface.co/settings/tokens แล้ววางในช่อง 🔑 HF Token ด้านบน / '
                'create a free token and paste it in the HF Token box above.'
            )
        raise gr.Error(str(e))
    except Exception as e:
        raise gr.Error(str(e))


def upload_local_model(zip_path, dir_name, progress=gr.Progress()):
    try:
        extraction_folder = os.path.join(rvc_models_dir, dir_name)
        if os.path.exists(extraction_folder):
            raise gr.Error(f'Voice model directory {dir_name} already exists! Choose a different name for your voice model.')

        zip_name = zip_path.name
        progress(0.5, desc='[~] Extracting zip...')
        extract_zip(extraction_folder, zip_name)
        return f'[+] {dir_name} Model successfully uploaded!'

    except Exception as e:
        raise gr.Error(str(e))


def filter_models(tags, query):
    models_table = []

    # no filter
    if len(tags) == 0 and len(query) == 0:
        for model in public_models['voice_models']:
            models_table.append([model['name'], model['description'], model['credit'], model['url'], model['tags']])

    # filter based on tags and query
    elif len(tags) > 0 and len(query) > 0:
        for model in public_models['voice_models']:
            if all(tag in model['tags'] for tag in tags):
                model_attributes = f"{model['name']} {model['description']} {model['credit']} {' '.join(model['tags'])}".lower()
                if query.lower() in model_attributes:
                    models_table.append([model['name'], model['description'], model['credit'], model['url'], model['tags']])

    # filter based on only tags
    elif len(tags) > 0:
        for model in public_models['voice_models']:
            if all(tag in model['tags'] for tag in tags):
                models_table.append([model['name'], model['description'], model['credit'], model['url'], model['tags']])

    # filter based on only query
    else:
        for model in public_models['voice_models']:
            model_attributes = f"{model['name']} {model['description']} {model['credit']} {' '.join(model['tags'])}".lower()
            if query.lower() in model_attributes:
                models_table.append([model['name'], model['description'], model['credit'], model['url'], model['tags']])

    return gr.update(value=models_table)


def pub_dl_autofill(pub_models, event: gr.SelectData):
    return gr.update(value=pub_models.loc[event.index[0], 'URL']), gr.update(value=pub_models.loc[event.index[0], 'Model Name'])


def swap_visibility():
    return gr.update(visible=True), gr.update(visible=False), gr.update(value=''), gr.update(value=None)


def process_file_upload(file):
    if file is None:
        return None, gr.update(value=''), ""
    title = clean_song_title(os.path.splitext(os.path.basename(file.name))[0])
    return file.name, gr.update(value=file.name), title


def show_hop_slider(pitch_detection_algo):
    if pitch_detection_algo == 'mangio-crepe':
        return gr.update(visible=True)
    else:
        return gr.update(visible=False)


CYBER_PLAYER_HEAD = """
<style>
.cyber-player-card {
    border: 1px solid var(--border-color-primary, #393939);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    border-radius: 12px;
    padding: 18px 22px;
    background: var(--block-background-fill, #161616);
    background-image: radial-gradient(640px 130px at 18% -10%, rgba(15, 98, 254, 0.13), transparent 70%);
    margin-top: 8px;
    font-family: var(--font, "IBM Plex Sans", "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif);
}
.cyber-controller-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--background-fill-secondary, #262626);
    border: 1px solid var(--border-color-primary, #393939);
    border-radius: var(--block-radius, 8px);
    padding: 10px 16px;
    margin-bottom: 14px;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.3);
}
.cyber-play-btn {
    width: 38px;
    height: 38px;
    min-width: 38px;
    border-radius: 50%;
    background: var(--primary-600, #0f62fe);
    color: var(--button-primary-text-color, #ffffff);
    border: none;
    font-size: 1rem;
    font-weight: bold;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(15, 98, 254, 0.35);
    transition: transform 0.15s cubic-bezier(0.32,0.72,0,1), background-color 0.15s cubic-bezier(0.32,0.72,0,1), box-shadow 0.15s cubic-bezier(0.32,0.72,0,1);
    user-select: none;
}
.cyber-play-btn:hover {
    transform: scale(1.06);
    background: var(--primary-500, #0353e9);
    box-shadow: 0 4px 12px rgba(15, 98, 254, 0.5);
}
.cyber-play-btn:active {
    transform: scale(0.96);
    background: var(--primary-700, #002d9c);
}
.cyber-time-display {
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
    font-variant-numeric: tabular-nums;
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--body-text-color-subdued, #c6c6c6);
    white-space: nowrap;
    min-width: 86px;
    user-select: none;
}
.cyber-seek-container {
    flex: 1;
    display: flex;
    align-items: center;
    margin: 0 4px;
}
.cyber-seek-slider {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 999px;
    outline: none;
    background: linear-gradient(to right, #0f62fe 0%, #0f62fe 0%, rgba(255, 255, 255, 0.15) 0%, rgba(255, 255, 255, 0.15) 100%);
    cursor: pointer;
    margin: 0;
    padding: 0;
}
.cyber-seek-slider::-webkit-slider-runnable-track {
    height: 6px;
    border-radius: 999px;
    background: transparent;
}
.cyber-seek-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--primary-600, #0f62fe);
    box-shadow: 0 0 6px rgba(15, 98, 254, 0.6);
    border: 2px solid #ffffff;
    cursor: pointer;
    margin-top: -4px;
    transition: transform 0.12s cubic-bezier(0.32,0.72,0,1), background-color 0.12s cubic-bezier(0.32,0.72,0,1);
}
.cyber-seek-slider:hover::-webkit-slider-thumb {
    transform: scale(1.2);
    background: var(--primary-500, #4589ff);
}
.cyber-seek-slider::-moz-range-track {
    height: 6px;
    border-radius: 999px;
    background: transparent;
}
.cyber-seek-slider::-moz-range-thumb {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--primary-600, #0f62fe);
    box-shadow: 0 0 6px rgba(15, 98, 254, 0.6);
    border: 2px solid #ffffff;
    cursor: pointer;
}
.cyber-vol-container {
    display: flex;
    align-items: center;
    gap: 6px;
}
.cyber-vol-btn {
    background: transparent;
    border: none;
    font-size: 1.05rem;
    cursor: pointer;
    padding: 0;
    margin: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.85;
    transition: opacity 0.15s cubic-bezier(0.32,0.72,0,1), transform 0.15s cubic-bezier(0.32,0.72,0,1);
}
.cyber-vol-btn:hover {
    opacity: 1;
    transform: scale(1.1);
}
.cyber-vol-slider {
    -webkit-appearance: none;
    appearance: none;
    width: 60px;
    height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.2);
    outline: none;
    cursor: pointer;
}
.cyber-vol-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--primary-500, #4589ff);
    box-shadow: 0 0 4px rgba(15, 98, 254, 0.5);
    cursor: pointer;
}
.cyber-vol-slider::-moz-range-thumb {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--primary-500, #4589ff);
    box-shadow: 0 0 4px rgba(15, 98, 254, 0.5);
    cursor: pointer;
}
/* ---- Motion refinement: one authored arrival, honest feedback ---- */
@keyframes cyber-arrive {
    from { opacity: 0; transform: translateY(14px); filter: blur(6px); }
    to { opacity: 1; transform: translateY(0); filter: blur(0); }
}
.cyber-arrive {
    animation: cyber-arrive 0.6s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes cyber-pulse-glow {
    0%, 100% { box-shadow: 0 2px 8px rgba(15, 98, 254, 0.35); }
    50% { box-shadow: 0 2px 18px rgba(15, 98, 254, 0.65); }
}
.cyber-player-card.playing .cyber-play-btn {
    animation: cyber-pulse-glow 2.2s cubic-bezier(0.32,0.72,0,1) infinite;
}
.lrc-report .lrc-item {
    animation: cyber-arrive 0.45s cubic-bezier(0.16, 1, 0.3, 1) both;
}
/* Gradio buttons: press physics matching the player */
button.gr-button-primary, button.gr-button-secondary {
    transition: transform 0.12s cubic-bezier(0.32,0.72,0,1), filter 0.15s cubic-bezier(0.32,0.72,0,1), box-shadow 0.15s cubic-bezier(0.32,0.72,0,1);
}
button.gr-button-primary:active, button.gr-button-secondary:active {
    transform: scale(0.97);
}
button.gr-button-primary:hover, button.gr-button-secondary:hover {
    filter: brightness(1.08);
}
/* Browser surfaces: focus and selection carry the Carbon palette.
   Scrollbars intentionally left at browser native per user feedback. */
.cyber-player-card :focus-visible,
button.gr-button-primary:focus-visible,
button.gr-button-secondary:focus-visible {
    outline: 2px solid var(--primary-500, #4589ff);
    outline-offset: 2px;
}
::selection {
    background: rgba(15, 98, 254, 0.45);
    color: #ffffff;
}
@media (prefers-reduced-motion: reduce) {
    .cyber-arrive, .lrc-report .lrc-item, .aig-acc {
        animation: none;
    }
    .cyber-player-card.playing .cyber-play-btn,
    .cyb-eq i, #aig-hero::before {
        animation: none;
    }
    .cyber-play-btn, .cyber-seek-slider::-webkit-slider-thumb,
    button.gr-button-primary, button.gr-button-secondary {
        transition: none;
    }
}
/* ---- Visible reskin: hero band, shells, island CTA, accent controls ----
   Gradio-official hooks only (#aig-hero, .aig-acc, .aig-cta); no guessed
   internal selectors. Single accent (#0f62fe), spring physics only. */
#aig-hero {
    text-align: center;
    padding: 30px 20px 24px;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 16px;
    background-color: var(--block-background-fill, #161616);
    background-image: radial-gradient(700px 160px at 50% -20%, rgba(15, 98, 254, 0.16), transparent 70%);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 4px;
}
.aig-acc {
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
    overflow: hidden;
}
.aig-cta button {
    border-radius: 999px;
    background-color: #0f62fe;
    background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.16) 0%, rgba(255, 255, 255, 0) 55%);
    box-shadow: 0 4px 16px rgba(15, 98, 254, 0.4);
    font-weight: 700;
    letter-spacing: 0.01em;
    padding-top: 12px;
    padding-bottom: 12px;
    transition: transform 0.12s cubic-bezier(0.32,0.72,0,1), filter 0.15s cubic-bezier(0.32,0.72,0,1), box-shadow 0.15s cubic-bezier(0.32,0.72,0,1);
}
.aig-cta button:hover {
    filter: brightness(1.1);
    box-shadow: 0 6px 24px rgba(15, 98, 254, 0.55);
}
.aig-cta button:active {
    transform: scale(0.98);
}
input[type="range"] {
    accent-color: #0f62fe;
}
/* ---- Interactive high-end: EQ, drift, entrances ----
   Transform/opacity only. Pointer-driven (no loops). Respects
   prefers-reduced-motion (see media block below).
   NOTE: cursor spotlight + custom scrollbars removed per user feedback. */
@keyframes eq-bounce {
    0%, 100% { transform: scaleY(0.3); }
    50% { transform: scaleY(1); }
}
.cyb-eq {
    display: none;
    align-items: flex-end;
    gap: 2px;
    height: 14px;
    margin-left: 2px;
}
.cyber-player-card.playing .cyb-eq {
    display: inline-flex;
}
.cyb-eq i {
    width: 3px;
    height: 100%;
    border-radius: 2px;
    background: var(--primary-500, #4589ff);
    transform-origin: bottom;
    animation: eq-bounce 0.9s cubic-bezier(0.32,0.72,0,1) infinite;
    animation-play-state: paused;
}
.cyber-player-card.playing .cyb-eq i {
    animation-play-state: running;
}
.cyb-eq i:nth-child(2) { animation-duration: 0.7s; animation-delay: 0.1s; }
.cyb-eq i:nth-child(3) { animation-duration: 1.1s; animation-delay: 0.25s; }
.cyb-eq i:nth-child(4) { animation-duration: 0.8s; animation-delay: 0.05s; }
.cyb-eq i:nth-child(5) { animation-duration: 1s; animation-delay: 0.3s; }
#aig-hero {
    position: relative;
    overflow: hidden;
}
#aig-hero::before {
    content: "";
    position: absolute;
    inset: -40%;
    pointer-events: none;
    background: radial-gradient(closest-side, rgba(15, 98, 254, 0.12), transparent 70%);
    animation: hero-drift 14s cubic-bezier(0.32,0.72,0,1) infinite alternate;
}
@keyframes hero-drift {
    from { transform: translate3d(-6%, -4%, 0); }
    to { transform: translate3d(6%, 5%, 0); }
}
.aig-acc {
    animation: cyber-arrive 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@media (max-width: 640px) {
    .cyber-controller-bar {
        flex-wrap: wrap;
        gap: 10px;
    }
    .cyber-seek-container {
        width: 100%;
        order: 3;
        margin: 4px 0;
    }
}
</style>
<script>
(function() {
    function fmtTime(s) {
        if (isNaN(s) || s < 0) return '0:00';
        var m = Math.floor(s / 60);
        var sec = Math.floor(s % 60);
        return m + ':' + (sec < 10 ? '0' : '') + sec;
    }
    function updateTrackGradient(slider, cur, dur) {
        var pct = dur > 0 ? (cur / dur) * 100 : 0;
        slider.style.background = 'linear-gradient(to right, #0f62fe 0%, #0f62fe ' + pct + '%, rgba(255,255,255,0.15) ' + pct + '%, rgba(255,255,255,0.15) 100%)';
    }
    window.initCyberAudio = function(cid) {
        var a = document.getElementById('audio_' + cid);
        var s = document.getElementById('seek_' + cid);
        var t = document.getElementById('time_' + cid);
        if (!a || !s) return;
        var dur = a.duration || 0;
        if (dur > 0) {
            s.max = dur;
            s.value = a.currentTime || 0;
            updateTrackGradient(s, a.currentTime || 0, dur);
            if (t) t.textContent = fmtTime(a.currentTime || 0) + ' / ' + fmtTime(dur);
        }
    };
    window.toggleCyberPlay = function(cid) {
        var a = document.getElementById('audio_' + cid);
        if (!a) return;
        if (a.paused) {
            a.play().catch(function(e){ console.warn(e); });
        } else {
            a.pause();
        }
    };
    function setCyberPlaying(cid, on) {
        var card = document.getElementById('card_' + cid);
        if (card) {
            if (on) { card.classList.add('playing'); }
            else { card.classList.remove('playing'); }
        }
    }
    window.onCyberPlay = function(cid) {
        var b = document.getElementById('play_' + cid);
        if (b) { b.innerHTML = '⏸'; b.title = 'Pause'; }
        setCyberPlaying(cid, true);
    };
    window.onCyberPause = function(cid) {
        var b = document.getElementById('play_' + cid);
        if (b) { b.innerHTML = '▶'; b.title = 'Play'; }
        setCyberPlaying(cid, false);
    };
    window.onCyberEnded = function(cid) {
        setCyberPlaying(cid, false);
        var b = document.getElementById('play_' + cid);
        var s = document.getElementById('seek_' + cid);
        var a = document.getElementById('audio_' + cid);
        var t = document.getElementById('time_' + cid);
        if (b) { b.innerHTML = '▶'; b.title = 'Play'; }
        if (s && a) {
            s.value = 0;
            updateTrackGradient(s, 0, a.duration || 0);
        }
        if (a && t) {
            t.textContent = '0:00 / ' + fmtTime(a.duration || 0);
        }
    };
    window.updateCyberTime = function(cid, a) {
        var s = document.getElementById('seek_' + cid);
        var t = document.getElementById('time_' + cid);
        if (!s || !a) return;
        var cur = a.currentTime || 0;
        var dur = a.duration || 0;
        if (!s.dataset.dragging) {
            s.value = cur;
            updateTrackGradient(s, cur, dur);
        }
        if (t) t.textContent = fmtTime(cur) + ' / ' + fmtTime(dur);
    };
    window.seekCyberInput = function(cid, val) {
        var s = document.getElementById('seek_' + cid);
        var a = document.getElementById('audio_' + cid);
        var t = document.getElementById('time_' + cid);
        if (!s) return;
        s.dataset.dragging = 'true';
        var dur = a ? (a.duration || 0) : 100;
        updateTrackGradient(s, parseFloat(val), dur);
        if (t) t.textContent = fmtTime(parseFloat(val)) + ' / ' + fmtTime(dur);
    };
    window.seekCyberChange = function(cid, val) {
        var s = document.getElementById('seek_' + cid);
        var a = document.getElementById('audio_' + cid);
        if (s) delete s.dataset.dragging;
        if (a) a.currentTime = parseFloat(val);
    };
    window.setCyberVolume = function(cid, val) {
        var a = document.getElementById('audio_' + cid);
        var vb = document.getElementById('volbtn_' + cid);
        if (!a) return;
        var v = parseFloat(val);
        a.volume = v;
        a.muted = (v === 0);
        if (vb) vb.innerHTML = (v === 0) ? '🔇' : (v < 0.5 ? '🔉' : '🔊');
    };
    window.toggleCyberMute = function(cid) {
        var a = document.getElementById('audio_' + cid);
        var vb = document.getElementById('volbtn_' + cid);
        var vs = document.getElementById('vol_' + cid);
        if (!a) return;
        a.muted = !a.muted;
        if (a.muted) {
            if (vb) vb.innerHTML = '🔇';
        } else {
            if (vb) vb.innerHTML = (a.volume < 0.5 ? '🔉' : '🔊');
            if (vs) vs.value = a.volume || 1;
        }
    };
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduceMotion) {
        document.querySelectorAll('.aig-cta button').forEach(function(btn) {
            btn.addEventListener('mousemove', function(e) {
                var r = btn.getBoundingClientRect();
                var dx = (e.clientX - (r.left + r.width / 2)) / r.width;
                var dy = (e.clientY - (r.top + r.height / 2)) / r.height;
                btn.style.transform = 'translate(' + (dx * 4).toFixed(2) + 'px,' + (dy * 4).toFixed(2) + 'px)';
            });
            btn.addEventListener('mouseleave', function() {
                btn.style.transform = '';
            });
        });
    }
})();
</script>
"""


def render_player_card(cover_path=None):
    if not cover_path or not os.path.exists(cover_path):
        return """
        <div class="cyber-arrive" style="
            border: 1px dashed var(--border-color-primary, #393939);
            border-radius: var(--block-radius, 8px);
            padding: 24px 20px;
            text-align: center;
            background: var(--block-background-fill, #161616);
            color: var(--body-text-color-subdued, #8d8d8d);
            margin-top: 8px;
        ">
            <div style="font-size: 1.6rem; margin-bottom: 6px;">🎧</div>
            <div style="font-size: 0.95rem; font-weight: 500; color: var(--body-text-color, #f4f4f4);">เครื่องเล่นเพลง AI / AI Cover Player (เล่นในเว็บได้ทันที 🔊)</div>
            <div style="font-size: 0.8rem; color: var(--body-text-color-subdued, #8d8d8d); margin-top: 4px;">เมื่อสร้างเพลงเสร็จ เครื่องเล่นเพลงพร้อมปุ่มดาวน์โหลดไฟล์จะปรากฏที่นี่ทันที</div>
        </div>
        """
    try:
        import base64
        import html
        import uuid
        with open(cover_path, "rb") as f:
            audio_bytes = f.read()
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        file_name = os.path.basename(cover_path)
        file_size_mb = len(audio_bytes) / (1024 * 1024)
        mime = "audio/mpeg" if cover_path.lower().endswith(".mp3") else "audio/wav"
        data_uri = f"data:{mime};base64,{b64_audio}"
        escaped_name = html.escape(file_name)
        download_attr = html.escape(file_name, quote=True)
        cid = f"cp_{uuid.uuid4().hex[:8]}"

        return f"""
        {CYBER_PLAYER_HEAD}
        <div id="card_{cid}" class="cyber-player-card cyber-arrive">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
                <div style="display: flex; align-items: center; gap: 12px; overflow: hidden;">
                    <span style="font-size: 1.6rem;">🎧</span>
                    <div style="overflow: hidden;">
                        <div style="font-weight: 700; font-size: 1.25rem; letter-spacing: -0.01em; line-height: 1.25; color: var(--body-text-color, #f4f4f4); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
                            {escaped_name}
                        </div>
                        <div style="display: inline-flex; align-items: center; gap: 6px; margin-top: 4px; padding: 2px 8px; border-radius: 4px; background: rgba(15, 98, 254, 0.12); border: 1px solid rgba(15, 98, 254, 0.25); font-size: 0.75rem; color: var(--primary-400, #4589ff); font-weight: 500;">
                            ⚡ AI Cover Ready · {file_size_mb:.2f} MB
                        </div>
                    </div>
                </div>
            </div>

            <audio id="audio_{cid}"
                   preload="auto"
                   style="display: none;"
                   src="{data_uri}"
                   onloadedmetadata="window.initCyberAudio && window.initCyberAudio('{cid}')"
                   ontimeupdate="window.updateCyberTime && window.updateCyberTime('{cid}', this)"
                   onplay="window.onCyberPlay && window.onCyberPlay('{cid}')"
                   onpause="window.onCyberPause && window.onCyberPause('{cid}')"
                   onended="window.onCyberEnded && window.onCyberEnded('{cid}')">
                เบราว์เซอร์ของคุณไม่รองรับการเล่นเสียง
            </audio>

            <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E"
                 onload="window.initCyberAudio && window.initCyberAudio('{cid}')"
                 style="display: none;" />

            <div class="cyber-controller-bar">
                <button id="play_{cid}" class="cyber-play-btn" type="button" onclick="window.toggleCyberPlay('{cid}')" title="Play">▶</button>
                <span class="cyb-eq" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
                <span id="time_{cid}" class="cyber-time-display">0:00 / --:--</span>
                <div class="cyber-seek-container">
                    <input id="seek_{cid}" class="cyber-seek-slider" type="range" min="0" max="100" value="0" step="0.1"
                           oninput="window.seekCyberInput('{cid}', this.value)"
                           onchange="window.seekCyberChange('{cid}', this.value)">
                </div>
                <div class="cyber-vol-container">
                    <button id="volbtn_{cid}" class="cyber-vol-btn" type="button" onclick="window.toggleCyberMute('{cid}')" title="Mute/Unmute">🔊</button>
                    <input id="vol_{cid}" class="cyber-vol-slider" type="range" min="0" max="1" step="0.05" value="1"
                           oninput="window.setCyberVolume('{cid}', this.value)" title="Volume">
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; align-items: center; gap: 12px; border-top: 1px solid var(--border-color-primary, rgba(255, 255, 255, 0.08)); padding-top: 12px;">
                <a href="{data_uri}" download="{download_attr}" style="
                    display: inline-flex;
                    align-items: center;
                    gap: 8px;
                    background: var(--button-primary-background-fill, #0f62fe);
                    color: var(--button-primary-text-color, #ffffff);
                    font-weight: 500;
                    font-size: 0.9rem;
                    padding: 8px 16px;
                    border-radius: var(--button-large-radius, 6px);
                    text-decoration: none;
                    box-shadow: 0 2px 8px rgba(15, 98, 254, 0.3);
                    transition: background-color 0.15s cubic-bezier(0.32,0.72,0,1), transform 0.15s cubic-bezier(0.32,0.72,0,1);
                ">
                    <span>💾</span> ดาวน์โหลดเพลง (.mp3)
                </a>
            </div>
        </div>
        """
    except Exception as e:
        return f'<div style="color: red; padding: 10px;">Error rendering player: {e}</div>'


if __name__ == '__main__':
    parser = ArgumentParser(description='Generate a AI cover song in the song_output/id directory.', add_help=True)
    parser.add_argument("--share", action="store_true", dest="share_enabled", default=False, help="Enable sharing")
    parser.add_argument("--builtin-player",  action="store_true", default=False, help="Use the builtin audio player")
    parser.add_argument("--listen", action="store_true", default=False, help="Make the WebUI reachable from your local network.")
    parser.add_argument('--listen-host', type=str, help='The hostname that the server will use.')
    parser.add_argument('--listen-port', type=int, help='The listening port that the server will use.')
    parser.add_argument('--theme', type=str, default="ibm-software/gradio-carbon-theme", help='Set the theme (default: ibm-software/gradio-carbon-theme)')
    parser.add_argument("--ssr", action="store_true", help="Enable SSR (Server-Side Rendering)")
    args = parser.parse_args()

    voice_models = get_current_models(rvc_models_dir)
    with open(os.path.join(rvc_models_dir, 'public_models.json'), encoding='utf8') as infile:
        public_models = json.load(infile)

    with gr.Blocks(title='AICoverGenWebUI', theme=args.theme, fill_width=True, fill_height=False, head=CYBER_PLAYER_HEAD) as app:

        gr.Label(f'AICoverGen WebUI {"ZeroGPU mode" if IS_ZERO_GPU else ""} created with ❤️', show_label=False, elem_id="aig-hero")
        if IS_ZERO_GPU:
            gr.Markdown(
                """
                <details>
                    <summary style="font-size: 1.5em;">⚠️ Important (click to expand)</summary>
                    <ul>
                        <li>🚀 This demo use a Zero GPU, which is available only for a limited time. It's recommended to use audio files that are no longer than 5 minutes. If you want to use it without time restrictions, you can duplicate the 'old CPU space'. ⏳</li>
                    </ul>
                </details>
                """
            )
            gr.Markdown("Duplicate the old CPU space for use in private: [![Duplicate this Space](https://huggingface.co/datasets/huggingface/badges/raw/main/duplicate-this-space-sm-dark.svg)](https://huggingface.co/spaces/r3gm/AICoverGen_old_stable_cpu?duplicate=true)\n\n") 

        # main tab
        with gr.Tab("สร้างเพลง / Generate"):

            with gr.Accordion('ตัวเลือกหลัก / Main Options', elem_classes=["aig-acc"]):
                with gr.Row():
                    with gr.Column():
                        rvc_model = gr.Dropdown(voice_models, label='โมเดลเสียง / Voice Models', info='โฟลเดอร์โมเดล "AICoverGen --> rvc_models" หลังเพิ่มโมเดลใหม่ให้กดปุ่มรีเฟรช / After adding new models, click refresh')
                        ref_btn = gr.Button('รีเฟรชโมเดล / Refresh 🔁', variant='primary')

                    with gr.Column(visible=False) as yt_link_col:
                        song_input = gr.Text(label='เพลงต้นฉบับ / Song input', info='ลิงก์เพลง YouTube หรือ path ไฟล์ในเครื่อง ถ้าจะอัปโหลดไฟล์ให้กดปุ่มด้านล่าง / Link to a YouTube song or full path to a local file.')
                        show_file_upload_button = gr.Button('อัปโหลดไฟล์แทน / Upload file instead')

                    with gr.Column(visible=True) as file_upload_col:
                        audio_extensions = ['.mp3', '.m4a', '.flac', '.wav', '.aac', '.ogg', '.wma', '.alac', '.aiff', '.opus', 'amr']
                        local_file = gr.File(label='ไฟล์เสียง / Audio file', interactive=True, type="filepath", file_types=audio_extensions, height=130)
                        song_title_input = gr.Textbox(label="ชื่อเพลงสำหรับตั้งชื่อไฟล์ผลลัพธ์ / Song Title (for output filename)", value="", placeholder="ระบบจะดึงชื่อเพลงให้อัตโนมัติ หรือพิมพ์แก้ไขได้ที่นี่...", lines=1)
                        if not IS_ZERO_GPU:
                            with gr.Row():
                                with gr.Row(scale=3):
                                    url_media_gui = gr.Textbox(value="", label="ใส่ URL / Enter URL", placeholder="www.youtube.com/watch?v=g_9rPvbENUw", lines=1)
                                with gr.Row(scale=2):
                                    url_button_gui = gr.Button("โหลด URL / Process URL", variant="secondary")
                                    clear_downloads_btn = gr.Button("🗑️ ล้างดาวน์โหลด / Clear", variant="stop")
                            url_button_gui.click(yt_download_for_ui, [url_media_gui], [local_file, song_title_input])
                            clear_downloads_btn.click(clear_downloads_action, outputs=[local_file, song_title_input])
                        song_input_file = gr.UploadButton('อัปโหลด / Upload 📂', file_types=['audio'], variant='primary', visible=False)
                        show_yt_link_button = gr.Button('วางลิงก์ YouTube/path ไฟล์แทน / Paste link instead', visible=False)
                        song_input_file.upload(process_file_upload, inputs=[song_input_file], outputs=[local_file, song_input, song_title_input])

                    with gr.Column():
                        pitch = gr.Slider(-3, 3, value=0, step=1, label='เปลี่ยนพิทช์ (เฉพาะเสียงร้อง / Vocals ONLY)', info='ปกติใช้ 1 แปลงชาย→หญิง และ -1 หญิง→ชาย (Octaves) / Use 1 for male-to-female, -1 for vice-versa.')
                        pitch_all = gr.Slider(-12, 12, value=0, step=1, label='เปลี่ยนพิทช์รวม / Overall Pitch', info='เปลี่ยนพิทช์/คีย์ทั้งเสียงร้องและดนตรีพร้อมกัน อาจลดคุณภาพเสียงเล็กน้อย (Semitones) / Changes pitch/key of vocals and instrumentals together.')
                        fast_mode = gr.Checkbox(True, label='⚡ โหมดความเร็วสูง / Fast Mode (2x เร็วกว่า)', info='ลดรอบคำนวณแยกเสียงลง 50% (ใช้เวลา ~2-3 นาที) / Halves separation passes for 2x faster conversion')
                    show_file_upload_button.click(swap_visibility, outputs=[file_upload_col, yt_link_col, song_input, local_file])
                    show_yt_link_button.click(swap_visibility, outputs=[yt_link_col, file_upload_col, song_input, local_file])

            with gr.Accordion('ตัวเลือกแปลงเสียง / Voice conversion', open=False, elem_classes=["aig-acc"]):
                with gr.Row():
                    index_rate = gr.Slider(0, 1, value=0.5, label='อัตรา Index / Index Rate', info="ควบคุมว่าให้เก็บสำเนียงของเสียง AI ไว้มากแค่ไหน / How much of the AI voice's accent to keep")
                    filter_radius = gr.Slider(0, 7, value=3, step=1, label='รัศมีฟิลเตอร์ / Filter radius', info='ถ้า >=3: ใช้ median filtering กับผล pitch ช่วยลดเสียงลมหายใจ / If >=3: median filtering on pitch, reduces breathiness')
                    rms_mix_rate = gr.Slider(0, 1, value=0.25, label='อัตราผสม RMS / RMS mix rate', info="เลียนแบบความดังเสียงต้นฉบับ (0) หรือใช้ความดังคงที่ (1) / Mimic original loudness (0) or fixed loudness (1)")
                    protect = gr.Slider(0, 0.5, value=0.33, label='อัตราป้องกันเสียง / Protect rate', info='ป้องกันเสียงพยัญชนะไร้เสียงและเสียงลมหายใจ ตั้ง 0.5 เพื่อปิด / Protect voiceless consonants and breath sounds.')
                    with gr.Column():
                        f0_method = gr.Dropdown(['rmvpe+', 'rmvpe', 'mangio-crepe'], value='rmvpe+', label='อัลกอริทึมจับพิทช์ / Pitch detection', info='แนะนำ rmvpe (เสียงชัด) รองลงมา mangio-crepe (เสียงนุ่ม) / Best is rmvpe (clarity), then mangio-crepe (smoother).')
                        crepe_hop_length = gr.Slider(32, 320, value=128, step=1, visible=False, label='ความถี่ตรวจจับ Crepe / Crepe hop length', info='ค่ายิ่งต่ำยิ่งแปลงนานและเสี่ยงเสียงแตก แต่จับพิทช์แม่นกว่า / Lower values: longer conversion, better pitch accuracy.')
                        f0_method.change(show_hop_slider, inputs=f0_method, outputs=crepe_hop_length)
                with gr.Row():
                    with gr.Row():
                        steps = gr.Slider(minimum=1, maximum=3, label="รอบการแปลง / Steps", value=1, step=1, interactive=True)
                    with gr.Row():
                        extra_denoise = gr.Checkbox(True, label='ลดนอยส์ / Denoise', info='ลดนอยส์เพิ่มเติมให้เสียงสะอาดขึ้น / Extra noise reduction for cleaner audio.')
                        keep_files = gr.Checkbox((False if IS_ZERO_GPU else True), label='เก็บไฟล์ระหว่างทาง / Keep intermediate files', info='เก็บไฟล์เสียงทั้งหมดใน song_output/id เช่น เสียงร้อง/ดนตรีแยก ไม่ติ๊กเพื่อประหยัดพื้นที่ / Keep all intermediate audio files. Uncheck to save space', interactive=(False if IS_ZERO_GPU else True))

            with gr.Accordion('ตัวเลือกผสมเสียง / Audio mixing', open=False, elem_classes=["aig-acc"]):
                gr.Markdown('### เปลี่ยนความดัง (เดซิเบล / decibels)')
                with gr.Row():
                    main_gain = gr.Slider(-20, 20, value=0, step=1, label='เสียงร้องหลัก / Main Vocals')
                    backup_gain = gr.Slider(-20, 20, value=0, step=1, label='เสียงร้องเสริม / Backup Vocals')
                    inst_gain = gr.Slider(-20, 20, value=0, step=1, label='ดนตรี / Music')

                gr.Markdown('### ควบคุมเสียงก้อง (Reverb) ของเสียง AI')
                with gr.Row():
                    reverb_rm_size = gr.Slider(0, 1, value=0.15, label='ขนาดห้อง / Room size', info='ห้องยิ่งใหญ่เสียงก้องยิ่งนาน / Larger room, longer reverb time')
                    reverb_wet = gr.Slider(0, 1, value=0.2, label='ระดับเสียงก้อง / Wetness', info='ระดับเสียง AI ที่มี reverb / Level of AI vocals with reverb')
                    reverb_dry = gr.Slider(0, 1, value=0.8, label='ระดับเสียงแห้ง / Dryness', info='ระดับเสียง AI ที่ไม่มี reverb / Level of AI vocals without reverb')
                    reverb_damping = gr.Slider(0, 1, value=0.7, label='ระดับดูดซับเสียง / Damping', info='การดูดซับความถี่สูงของ reverb / Absorption of high frequencies')

                gr.Markdown('### รูปแบบไฟล์เสียง / Output Format')
                output_format = gr.Dropdown(['mp3', 'wav'], value='mp3', label='ชนิดไฟล์ / Output file type', info='mp3: ไฟล์เล็ก คุณภาพพอใช้ wav: ไฟล์ใหญ่ คุณภาพดีสุด / mp3: small file, decent quality. wav: large file, best quality')

            with gr.Accordion('ตรวจสอบเนื้อร้อง / Lyrics Checker (optional)', open=False, elem_classes=["aig-acc"]):
                gr.Markdown('ฟังเสียงร้องด้วย ASR แล้วเทียบกับเนื้อร้องที่ให้มา — ปิดไว้โดยปริยาย ไม่กระทบการสร้างเพลงหลัก / Transcribes vocals and compares with your reference lyrics. Off by default; never blocks cover generation.')
                lyrics_enable = gr.Checkbox(False, label='เปิดใช้ Lyrics Checker / Enable', info='ต้องติดตั้ง faster-whisper ก่อน (optional) / Requires faster-whisper (optional dep)')
                with gr.Row():
                    lyrics_ref = gr.Textbox(label='เนื้อร้องอ้างอิง / Reference lyrics', placeholder='วางเนื้อร้องที่นี่... / Paste expected lyrics here', lines=5)
                    with gr.Column():
                        lyrics_lang = gr.Dropdown(['auto', 'th', 'en'], value='auto', label='ภาษา / Language', info='auto = ตรวจอัตโนมัติ (อาจผิดสำหรับเพลงร้อง) / Auto-detect may err on singing')
                        lyrics_model = gr.Dropdown(['tiny', 'base', 'small'], value='base', label='ขนาดโมเดล ASR / ASR model', info='base+CPU ปลอดภัยกับ VRAM 4GB / Safe default for 4GB VRAM')
                        lyrics_device = gr.Dropdown(['cpu', 'cuda'], value='cpu', label='อุปกรณ์ / Device', info='ใช้ cpu เพื่อไม่แย่ง VRAM กับ RVC / cpu avoids VRAM contention')
                        lyrics_timestamp = gr.Dropdown(['word', 'segment', 'none'], value='word', label='เวลา / Timestamps', info='word=เวลาระดับคำ segment=เวลาระดับช่วง none=ไม่แสดงเวลา / word-level, segment-level, or none')
                lyrics_btn = gr.Button('ตรวจสอบเนื้อร้อง / Check lyrics 🔍', variant='secondary')
                lyrics_report = gr.HTML('<div style="color:#8d8d8d;">ติ๊กเปิดใช้แล้วกดปุ่มตรวจสอบ / Enable and press Check.</div>')

                def run_lyrics_check(audio_file, enabled, ref, lang, model, device, timestamp_mode):
                    if not enabled:
                        return '<div>☑️ Lyrics Checker ปิดอยู่ — เปิดสวิตช์ก่อน / Checker is disabled.</div>'
                    if not audio_file:
                        return '<div style="color:#fa4d56;">❌ กรุณาเลือกไฟล์เสียงก่อน / Please select an audio file first.</div>'
                    try:
                        from lyrics import analyze_vocals
                    except ImportError as e:
                        return f'<div style="color:#fa4d56;">❌ โมดูล lyrics โหลดไม่ได้: {e}</div>'
                    rep = analyze_vocals(audio_file, ref or '', lang, model, device, timestamp_mode=timestamp_mode or 'word')
                    return rep.to_html()

                lyrics_btn.click(run_lyrics_check,
                                 inputs=[local_file, lyrics_enable, lyrics_ref, lyrics_lang, lyrics_model, lyrics_device, lyrics_timestamp],
                                 outputs=[lyrics_report])

            with gr.Accordion('ตรวจสอบหลัง RVC / Post-RVC Analysis (optional)', open=False, elem_classes=["aig-acc"]):
                gr.Markdown('เทียบเสียงร้องต้นฉบับกับเสียงหลัง RVC ด้วย ASR verse-by-verse — ปิดไว้โดยปริยาย ไม่แตะการตั้งค่า RVC และไม่ลบไฟล์ cover / Compares pre/post-RVC vocals. Off by default; never retunes RVC or deletes outputs.')
                postrvc_enable = gr.Checkbox(False, label='เปิดใช้ Post-RVC Analysis / Enable', info='ต้องติดตั้ง faster-whisper ก่อน (optional) / Requires faster-whisper (optional dep)')
                with gr.Row():
                    postrvc_src = gr.File(label='เสียงต้นฉบับ / Source vocal (เช่น *_Vocals_Main_DeReverb.wav)', interactive=True, type="filepath", file_types=audio_extensions, height=130)
                    postrvc_conv = gr.File(label='เสียงหลัง RVC / Converted vocal (เช่น *_rmvpe_s1.wav)', interactive=True, type="filepath", file_types=audio_extensions, height=130)
                with gr.Row():
                    postrvc_ref = gr.Textbox(label='เนื้อเพลงอ้างอิง / Reference lyrics (optional)', placeholder='ไม่บังคับ — ถ้าเว้นว่างจะเทียบ Transcript สองไฟล์กันเอง / Optional: without it, compares the two transcripts', lines=3)
                    with gr.Column():
                        postrvc_lang = gr.Dropdown(['auto', 'th', 'en'], value='auto', label='ภาษา / Language', info='ใช้ค่าเดียวกันทั้งสองฝั่งเพื่อให้เทียบกันได้ / Same setting on both sides')
                        postrvc_model = gr.Dropdown(['tiny', 'base', 'small'], value='base', label='ขนาดโมเดล ASR / ASR model', info='base+CPU ปลอดภัยกับ VRAM 4GB / Safe default for 4GB VRAM')
                        postrvc_device = gr.Dropdown(['cpu', 'cuda'], value='cpu', label='อุปกรณ์ / Device', info='รันหลัง RVC เท่านั้น ไม่แย่ง VRAM ตอนแปลงเสียง / Runs after RVC only')
                        postrvc_timestamp = gr.Dropdown(['word', 'segment', 'none'], value='word', label='เวลา / Timestamps', info='เวลาของเคสเทียบอ้างอิงไฟล์หลัง RVC / Cross-case times reference the converted file')
                postrvc_btn = gr.Button('ตรวจสอบหลัง RVC / Check post-RVC 🔍', variant='secondary')
                postrvc_report = gr.HTML('<div style="color:#8d8d8d;">ติ๊กเปิดใช้ เลือกไฟล์ทั้งสองฝั่ง แล้วกดปุ่มตรวจสอบ / Enable, pick both files, press Check.</div>')

                def run_postrvc_check(src_file, conv_file, enabled, ref, lang, model, device, timestamp_mode):
                    if not enabled:
                        return '<div>☑️ Post-RVC Analysis ปิดอยู่ — เปิดสวิตช์ก่อน / Analyzer is disabled.</div>'
                    if not src_file or not conv_file:
                        return '<div style="color:#fa4d56;">❌ กรุณาเลือกไฟล์เสียงทั้งต้นฉบับและหลัง RVC / Please select both vocal files.</div>'
                    try:
                        from lyrics.postrvc import analyze_post_rvc
                    except ImportError as e:
                        return f'<div style="color:#fa4d56;">❌ โมดูล postrvc โหลดไม่ได้: {e}</div>'
                    rep = analyze_post_rvc(src_file, conv_file, ref or '', lang, model, device, timestamp_mode=timestamp_mode or 'word')
                    return rep.to_html()

                postrvc_btn.click(run_postrvc_check,
                                  inputs=[postrvc_src, postrvc_conv, postrvc_enable, postrvc_ref, postrvc_lang, postrvc_model, postrvc_device, postrvc_timestamp],
                                  outputs=[postrvc_report])

            with gr.Accordion('ตรวจทานเนื้อร้อง / Lyric Review (optional)', open=False, elem_classes=["aig-acc"]):
                gr.Markdown('ตรวจทานและแก้ไขเนื้อร้องทีละจุดจากผล ASR — ต้นฉบับ ASR ไม่ถูกแตะ การแก้ต้องกดยืนยันทุกครั้ง ปิดไว้โดยปริยาย / Review and correct lyrics item by item. Original ASR transcript is immutable; every edit needs explicit confirm. Off by default.')
                review_enable = gr.Checkbox(False, label='เปิดใช้ Lyric Review / Enable', info='ต้องติดตั้ง faster-whisper ก่อน (optional) / Requires faster-whisper (optional dep)')
                with gr.Row():
                    review_audio = gr.File(label='ไฟล์เสียง / Audio file', interactive=True, type="filepath", file_types=audio_extensions, height=130)
                    review_ref = gr.Textbox(label='เนื้อเพลงอ้างอิง / Reference lyrics', placeholder='วางเนื้อร้องที่นี่... / Paste expected lyrics here', lines=3)
                with gr.Row():
                    with gr.Column():
                        review_lang = gr.Dropdown(['auto', 'th', 'en'], value='auto', label='ภาษา / Language', info='auto = ตรวจอัตโนมัติ (อาจผิดสำหรับเพลงร้อง) / Auto-detect may err on singing')
                        review_model = gr.Dropdown(['tiny', 'base', 'small'], value='base', label='ขนาดโมเดล ASR / ASR model', info='base+CPU ปลอดภัยกับ VRAM 4GB / Safe default for 4GB VRAM')
                    with gr.Column():
                        review_device = gr.Dropdown(['cpu', 'cuda'], value='cpu', label='อุปกรณ์ / Device', info='ใช้ cpu เพื่อไม่แย่ง VRAM กับ RVC / cpu avoids VRAM contention')
                        review_timestamp = gr.Dropdown(['word', 'segment', 'none'], value='word', label='เวลา / Timestamps', info='word=เวลาระดับคำ segment=เวลาระดับช่วง none=ไม่แสดงเวลา')
                review_start = gr.Button('เริ่มตรวจทาน / Start review 🔍', variant='secondary')
                review_state = gr.State(None)
                review_status = gr.HTML('<div style="color:#8d8d8d;">ติ๊กเปิดใช้ เลือกไฟล์ แล้วกดเริ่มตรวจทาน / Enable, pick a file, press Start.</div>')
                review_items = gr.HTML('')
                with gr.Row():
                    review_picker = gr.Dropdown([], label='เลือกรายการ / Pick item', info='รายการที่ต้องตรวจทาน / Items to review')
                    review_edit = gr.Textbox(label='ข้อความแก้ไข / Corrected text', placeholder='พิมพ์ข้อความที่ถูกต้อง หรือเว้นไว้แล้วกดยืนยันหากต้นฉบับถูกแล้ว')
                with gr.Row():
                    review_apply = gr.Button('บันทึกการแก้ / Apply edit')
                    review_confirm = gr.Button('ยืนยันต้นฉบับถูกแล้ว / Confirm original')
                    review_revert = gr.Button('ย้อนกลับ / Revert')
                with gr.Row():
                    review_preview_btn = gr.Button('ดู Preview + ตรวจซ้ำ / Preview & recheck')
                    review_save = gr.Button('บันทึก JSON / Save')
                    review_discard = gr.Button('ทิ้ง / Discard', variant='stop')
                review_detail = gr.HTML('')
                review_preview_box = gr.HTML('')

                def _review_items_html(state):
                    import html as _h
                    if not state:
                        return ''
                    rows = []
                    for it in state.get('items', []):
                        mark = '✅' if it.get('reviewed') else '🔍'
                        t = (f"{it['start_time']:.1f}s–{it['end_time']:.1f}s"
                             if it.get('start_time') is not None and it.get('end_time') is not None else '—')
                        corr = f" → <b>{_h.escape(it['corrected_text'])}</b>" if it.get('corrected_text') is not None else ''
                        rows.append(
                            f"<div>{mark} <b>{_h.escape(it['id'])}</b> [{_h.escape(it['status'])}] "
                            f"<span>{_h.escape(t)}</span><br>อ้างอิง: {_h.escape(it.get('ref_text') or '—')} → "
                            f"ฟังได้: {_h.escape(it.get('hyp_text') or '—')}{corr}</div>")
                    if not rows:
                        return '<div>✅ ไม่พบจุดที่ต้องตรวจทาน / Nothing to review.</div>'
                    return '<div>' + ''.join(rows) + '</div>'

                def _detail_for(state, item_id):
                    import html as _h
                    for it in (state or {}).get('items', []):
                        if it['id'] == item_id:
                            prefill = it['corrected_text'] if it.get('corrected_text') is not None else it.get('hyp_text', '')
                            return (f"<div><b>{_h.escape(it['id'])}</b> [{_h.escape(it['status'])}]<br>"
                                    f"อ้างอิง: {_h.escape(it.get('ref_text') or '—')}<br>"
                                    f"ฟังได้ (ต้นฉบับ ASR): {_h.escape(it.get('hyp_text') or '—')}<br>"
                                    f"เหตุผล: {_h.escape(it.get('reason') or '')}</div>"), prefill
                    return '<div>❌ ไม่พบรายการ / Item not found.</div>', ''

                def run_review_start(audio_file, enabled, ref, lang, model, device, timestamp_mode):
                    if not enabled:
                        return None, '<div>☑️ Lyric Review ปิดอยู่ — เปิดสวิตช์ก่อน / Review is disabled.</div>', '', gr.Dropdown(choices=[]), '', ''
                    if not audio_file:
                        return None, '<div style="color:#fa4d56;">❌ กรุณาเลือกไฟล์เสียงก่อน / Please select an audio file first.</div>', '', gr.Dropdown(choices=[]), '', ''
                    try:
                        from lyrics import analyze_vocals
                        from lyrics.review import build_review, session_to_dict, validate_item_audio
                    except ImportError as e:
                        return None, f'<div style="color:#fa4d56;">❌ โมดูล review โหลดไม่ได้: {e}</div>', '', gr.Dropdown(choices=[]), '', ''
                    rep = analyze_vocals(audio_file, ref or '', lang, model, device, timestamp_mode=timestamp_mode or 'word')
                    if rep.error:
                        import html as _h
                        from lyrics.review import build_review as _br
                        sess = _br(rep, audio_file)
                        return session_to_dict(sess), f'<div>❌ ASR_FAILED: {_h.escape(rep.error)}</div>', '', gr.Dropdown(choices=[]), '', ''
                    sess = build_review(rep, audio_file)
                    issues = []
                    for it in sess.items:
                        issues.extend(f"{it.id}: {x}" for x in validate_item_audio(sess, it.id))
                    extra = ('<div>⚠️ ' + '<br>'.join(issues) + '</div>') if issues else ''
                    if sess.status == 'MATCH':
                        return session_to_dict(sess), '<div>✅ ตรงกันทั้งหมด / All match.</div>', '', gr.Dropdown(choices=[]), '', ''
                    if sess.status == 'NO_REFERENCE':
                        return session_to_dict(sess), '<div>⚠️ ไม่มีเนื้อเพลงอ้างอิง — ตรวจทานไม่ได้ / No reference.</div>', '', gr.Dropdown(choices=[]), '', ''
                    choices = [it.id for it in sess.items]
                    state_dict = session_to_dict(sess)
                    first_detail, first_prefill = _detail_for(state_dict, choices[0] if choices else '')
                    return (state_dict,
                            f'<div>🔍 พบ {len(choices)} จุดให้ตรวจทาน / {len(choices)} items to review.</div>' + extra,
                            _review_items_html(state_dict),
                            gr.Dropdown(choices=choices, value=choices[0] if choices else None),
                            first_detail, first_prefill)

                def run_review_detail(state, item_id):
                    if not state or not item_id:
                        return '', ''
                    return _detail_for(state, item_id)

                def _refresh_ui(state):
                    import html as _h
                    done = sum(1 for it in state.get('items', []) if it.get('reviewed'))
                    total = len(state.get('items', []))
                    return (state, _review_items_html(state),
                            f'<div>ตรวจแล้ว {done}/{total} / Reviewed {done}/{total}.</div>')

                def run_review_apply(state, item_id, text):
                    if not state:
                        return None, '', '<div>❌ เริ่มตรวจทานก่อน / Start a review first.</div>'
                    if not item_id:
                        return state, _review_items_html(state), '<div>❌ เลือกรายการก่อน / Pick an item first.</div>'
                    try:
                        from lyrics.review import apply_correction, session_from_dict, session_to_dict as _to
                    except ImportError as e:
                        return state, '', f'<div>❌ {e}</div>'
                    sess = session_from_dict(state)
                    try:
                        apply_correction(sess, item_id, text or '', actor='user')
                    except ValueError as e:
                        return state, _review_items_html(state), f'<div>❌ {e}</div>'
                    import html as _h
                    new_state, items_html, _progress = _refresh_ui(_to(sess))
                    return new_state, items_html, (f'<div>✏️ บันทึกการแก้ {_h.escape(item_id)} แล้ว — กดยืนยันเพื่อปิดรายการ / Edit saved, press Confirm to close.</div>')

                def run_review_confirm(state, item_id):
                    if not state or not item_id:
                        return (state or None), '', '<div>❌ เลือกรายการก่อน / Pick an item first.</div>'
                    try:
                        from lyrics.review import confirm_correction, session_from_dict, session_to_dict as _to
                    except ImportError as e:
                        return state, '', f'<div>❌ {e}</div>'
                    sess = session_from_dict(state)
                    try:
                        confirm_correction(sess, item_id, actor='user')
                    except ValueError as e:
                        return state, _review_items_html(state), f'<div>❌ {e}</div>'
                    new_state, items_html, _progress = _refresh_ui(_to(sess))
                    return new_state, items_html, '<div>✅ ยืนยันแล้ว / Confirmed.</div>'

                def run_review_revert(state, item_id):
                    if not state or not item_id:
                        return (state or None), '', '<div>❌ เลือกรายการก่อน / Pick an item first.</div>'
                    try:
                        from lyrics.review import revert_correction, session_from_dict, session_to_dict as _to
                    except ImportError as e:
                        return state, '', f'<div>❌ {e}</div>'
                    sess = session_from_dict(state)
                    try:
                        revert_correction(sess, item_id, actor='user')
                    except ValueError as e:
                        return state, _review_items_html(state), f'<div>❌ {e}</div>'
                    new_state, items_html, _progress = _refresh_ui(_to(sess))
                    return new_state, items_html, '<div>↩️ ย้อนกลับแล้ว / Reverted.</div>'

                def run_review_preview(state):
                    if not state:
                        return '<div>❌ เริ่มตรวจทานก่อน / Start a review first.</div>'
                    try:
                        from lyrics.review import preview_corrected_text, recheck_reviewed, session_from_dict
                    except ImportError as e:
                        return f'<div>❌ {e}</div>'
                    import html as _h
                    sess = session_from_dict(state)
                    prev = preview_corrected_text(sess)
                    try:
                        out = recheck_reviewed(sess, sess.language)
                        recheck = f'ตรวจซ้ำ: เหลือ {len(out.mismatches)} จุด / Remaining: {len(out.mismatches)}.'
                    except ValueError as e:
                        recheck = f'ตรวจซ้ำไม่ได้: {e}'
                    return (f'<div><b>Preview (ไม่แตะต้นฉบับ ASR):</b><br>{_h.escape(prev[:2000])}'
                            f'{"…" if len(prev) > 2000 else ""}</div><div>{_h.escape(recheck)}</div>')

                def run_review_save(state):
                    if not state:
                        return '<div>❌ ไม่มี session ให้บันทึก / Nothing to save.</div>'
                    try:
                        from lyrics.review import save_session, session_from_dict
                    except ImportError as e:
                        return f'<div>❌ {e}</div>'
                    import html as _h
                    sess = session_from_dict(state)
                    if not sess.audio_path:
                        return '<div>❌ ไม่พบ path ไฟล์เสียง / No audio path.</div>'
                    path = sess.audio_path + '.review.json'
                    try:
                        save_session(sess, path)
                    except OSError as e:
                        return f'<div>❌ บันทึกไม่ได้: {_h.escape(str(e))}</div>'
                    done = sum(1 for it in sess.items if it.reviewed)
                    total = len(sess.items)
                    return (f'<div>💾 บันทึกแล้ว: {_h.escape(path)} / Saved. '
                            f'(ตรวจแล้ว {done}/{total} / Reviewed {done}/{total}.)</div>')

                def run_review_discard():
                    return None, '<div>🗑️ ทิ้ง session แล้ว / Discarded. ต้นฉบับ ASR ไม่ถูกแตะต้อง</div>', '', gr.Dropdown(choices=[]), '', ''

                review_start.click(run_review_start,
                                   inputs=[review_audio, review_enable, review_ref, review_lang, review_model, review_device, review_timestamp],
                                   outputs=[review_state, review_status, review_items, review_picker, review_detail, review_edit])
                review_picker.change(run_review_detail,
                                     inputs=[review_state, review_picker],
                                     outputs=[review_detail, review_edit])
                review_apply.click(run_review_apply,
                                   inputs=[review_state, review_picker, review_edit],
                                   outputs=[review_state, review_items, review_status])
                review_confirm.click(run_review_confirm,
                                     inputs=[review_state, review_picker],
                                     outputs=[review_state, review_items, review_status])
                review_revert.click(run_review_revert,
                                    inputs=[review_state, review_picker],
                                    outputs=[review_state, review_items, review_status])
                review_preview_btn.click(run_review_preview,
                                         inputs=[review_state],
                                         outputs=[review_preview_box])
                review_save.click(run_review_save,
                                  inputs=[review_state],
                                  outputs=[review_status])
                review_discard.click(run_review_discard,
                                     inputs=[],
                                     outputs=[review_state, review_status, review_items, review_picker, review_detail, review_edit])

            with gr.Row():
                clear_btn = gr.ClearButton(value='ล้าง / Clear', components=[song_input, rvc_model, keep_files, local_file, song_title_input, fast_mode])
                generate_btn = gr.Button("สร้างเพลง / Generate", variant='primary', elem_classes=["aig-cta"])

            with gr.Row():
                ai_cover_player = gr.HTML(render_player_card(None))
            clear_btn.add([ai_cover_player])
            gr.Markdown("- You can also try `AICoverGen❤️` in Colab’s free tier, which provides free GPU [link](https://github.com/R3gm/AICoverGen?tab=readme-ov-file#aicovergen).")

            ref_btn.click(update_models_list, None, outputs=rvc_model)
            is_webui = gr.Number(value=1, visible=False)

            def run_cover_webui(*args):
                free_lyrics_models()
                cover_path = song_cover_pipeline(*args)
                return render_player_card(cover_path)

            generate_btn.click(run_cover_webui,
                               inputs=[local_file, rvc_model, pitch, keep_files, is_webui, main_gain, backup_gain,
                                       inst_gain, index_rate, filter_radius, rms_mix_rate, f0_method, crepe_hop_length,
                                       protect, pitch_all, reverb_rm_size, reverb_wet, reverb_dry, reverb_damping,
                                       output_format, extra_denoise, steps, song_title_input, fast_mode],
                               outputs=[ai_cover_player])
            clear_btn.click(lambda: [0, 0, 0, 0, 0.5, 3, 0.25, 0.33, 'rmvpe+', 128, 0, 0.15, 0.2, 0.8, 0.7, 'mp3', render_player_card(None), True, 1, "", True],
                            outputs=[pitch, main_gain, backup_gain, inst_gain, index_rate, filter_radius, rms_mix_rate,
                                     protect, f0_method, crepe_hop_length, pitch_all, reverb_rm_size, reverb_wet,
                                     reverb_dry, reverb_damping, output_format, ai_cover_player, extra_denoise, steps, song_title_input, fast_mode])

        # Download tab
        with gr.Tab('โหลดโมเดล / Download model'):

            hf_token = gr.Text(label='🔑 HF Token (เฉพาะโมเดลที่ต้อง login / only if download fails with 401)',
                               info='สร้างฟรีที่ huggingface.co/settings/tokens — ข้ามได้ถ้าโหลดปกติสำเร็จ / Free token, skip unless you get a 401 error.',
                               type='password')

            with gr.Tab('จากลิงก์ / From URL'):
                with gr.Row():
                    model_zip_link = gr.Text(label='ลิงก์โหลดโมเดล / Download link', info='ต้องเป็น zip ที่มีไฟล์ .pth และไฟล์ .index (ถ้ามี) / Must be a zip with a .pth file and optional .index.')
                    model_name = gr.Text(label='ตั้งชื่อโมเดล / Name your model', info='ตั้งชื่อไม่ซ้ำกับโมเดลอื่น / Give it a unique name.')

                with gr.Row():
                    download_btn = gr.Button('โหลดเลย / Download 🌐', variant='primary', scale=19)
                    dl_output_message = gr.Text(label='ผลลัพธ์ / Output Message', interactive=False, scale=20)

                download_btn.click(download_online_model, inputs=[model_zip_link, model_name, hf_token], outputs=dl_output_message)

                gr.Markdown('## ตัวอย่าง / Input Examples')
                gr.Examples(
                    [
                        ['https://huggingface.co/MrDawg/ToothBrushing/resolve/main/ToothBrushing.zip?download=true', 'ToothBrushing'],
                        ['https://huggingface.co/analogspiderweb/analogspiderweb_RVC/resolve/main/villager.zip?download=true', 'Minecraft_Villager'],
                        ['https://huggingface.co/imam2023/RVC_AI_Model/resolve/main/Ado%20(2022%20-%202026)%20-%20Weights%20Model.zip?download=true', 'Ado'],
                        ['https://huggingface.co/Eddycrack864/KOBASOLO-AI-Voice/resolve/main/kobasolo.zip', 'KOBASOLO'],
                        ['https://huggingface.co/2star/YOASOBI/resolve/main/YOASOBI_VER1_e300_s10800.zip?download=true', 'YOASOBI'],
                        ['https://huggingface.co/phant0m4r/LiSA/resolve/main/LiSA.zip', 'Lisa'],
                        ['https://pixeldrain.com/u/3tJmABXA', 'Gura'],
                        ['https://huggingface.co/Kit-Lemonfoot/kitlemonfoot_rvc_models/resolve/main/AZKi%20(Hybrid).zip', 'Azki']
                    ],
                    [model_zip_link, model_name],
                    [],
                    download_online_model,
                    cache_examples=False,
                )

            with gr.Tab('จากคลังโมเดล / Public Index'):

                gr.Markdown('## วิธีใช้ / How to use')
                gr.Markdown('- กดปุ่มโหลดตารางโมเดล / Click Initialize public models table')
                gr.Markdown('- กรองโมเดลด้วย tags หรือช่องค้นหา / Filter models using tags or search bar')
                gr.Markdown('- เลือกแถวเพื่อเติมลิงก์และชื่ออัตโนมัติ / Select a row to autofill link and name')
                gr.Markdown('- กด Download')

                with gr.Row():
                    pub_zip_link = gr.Text(label='ลิงก์โหลดโมเดล / Download link')
                    pub_model_name = gr.Text(label='ชื่อโมเดล / Model name')

                with gr.Row():
                    download_pub_btn = gr.Button('Download 🌐', variant='primary', scale=19)
                    pub_dl_output_message = gr.Text(label='ผลลัพธ์ / Output Message', interactive=False, scale=20)

                filter_tags = gr.CheckboxGroup(value=[], label='แสดงโมเดลตาม tags / Show models with tags', choices=[])
                search_query = gr.Text(label='ค้นหา / Search')
                load_public_models_button = gr.Button(value='โหลดตารางโมเดล / Initialize table', variant='primary')

                public_models_table = gr.DataFrame(value=[], headers=['Model Name', 'Description', 'Credit', 'URL', 'Tags'], label='โมเดลสาธารณะ / Available Public Models', interactive=False)
                public_models_table.select(pub_dl_autofill, inputs=[public_models_table], outputs=[pub_zip_link, pub_model_name])
                load_public_models_button.click(load_public_models, outputs=[public_models_table, filter_tags])
                search_query.change(filter_models, inputs=[filter_tags, search_query], outputs=public_models_table)
                filter_tags.change(filter_models, inputs=[filter_tags, search_query], outputs=public_models_table)
                download_pub_btn.click(download_online_model, inputs=[pub_zip_link, pub_model_name, hf_token], outputs=pub_dl_output_message)

        # Upload tab
        with gr.Tab('อัปโหลดโมเดล / Upload model'):
            gr.Markdown('## อัปโหลดโมเดล RVC v2 ที่เทรนเอง / Upload locally trained RVC v2 model')
            gr.Markdown('- หาไฟล์โมเดล (โฟลเดอร์ weights) และไฟล์ index (โฟลเดอร์ logs/[name]) / Find model + optional index file')
            gr.Markdown('- บีบอัดเป็นไฟล์ zip / Compress files into zip')
            gr.Markdown('- อัปโหลด zip แล้วตั้งชื่อไม่ซ้ำ / Upload zip and give it a unique name')
            gr.Markdown('- กด Upload model')

            with gr.Row():
                with gr.Column():
                    zip_file = gr.File(label='ไฟล์ zip / Zip file')

                local_model_name = gr.Text(label='ชื่อโมเดล / Model name')

            with gr.Row():
                model_upload_button = gr.Button('อัปโหลดโมเดล / Upload model', variant='primary', scale=19)
                local_upload_output_message = gr.Text(label='ผลลัพธ์ / Output Message', interactive=False, scale=20)
                model_upload_button.click(upload_local_model, inputs=[zip_file, local_model_name], outputs=local_upload_output_message)

    @app.app.middleware("http")
    async def enforce_inline_audio_middleware(request, call_next):
        response = await call_next(request)
        path = str(request.url.path).lower()
        if "/gradio_api/file=" in path or path.endswith((".mp3", ".wav")):
            ct = response.headers.get("content-type", "")
            if path.endswith(".mp3") or "audio" in ct:
                if not ct or "octet-stream" in ct:
                    response.headers["content-type"] = "audio/mpeg" if path.endswith(".mp3") else "audio/wav"
                cd = response.headers.get("content-disposition", "")
                if "attachment" in cd:
                    response.headers["content-disposition"] = cd.replace("attachment", "inline")
                response.headers["accept-ranges"] = "bytes"
        return response

    app.launch(
        share=args.share_enabled,
        debug=args.share_enabled,
        show_error=True,
        # enable_queue=True,
        server_name=None if not args.listen else (args.listen_host or '0.0.0.0'),
        server_port=args.listen_port,
        ssr_mode=args.ssr,
        allowed_paths=[output_dir, BASE_DIR, tempfile.gettempdir()]
    )
