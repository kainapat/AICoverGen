import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from argparse import ArgumentParser
import spaces
import gradio as gr
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


def get_current_models(models_dir):
    models_list = os.listdir(models_dir)
    items_to_remove = ['hubert_base.pt', 'MODELS.txt', 'public_models.json', 'rmvpe.pt']
    return [item for item in models_list if item not in items_to_remove]


def update_models_list():
    models_l = get_current_models(rvc_models_dir)
    return gr.update(choices=models_l)


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

    with gr.Blocks(title='AICoverGenWebUI', theme=args.theme, fill_width=True, fill_height=False) as app:

        gr.Label(f'AICoverGen WebUI {"ZeroGPU mode" if IS_ZERO_GPU else ""} created with ❤️', show_label=False)
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

            with gr.Accordion('ตัวเลือกหลัก / Main Options'):
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
                                with gr.Row(scale=2):
                                    url_media_gui = gr.Textbox(value="", label="ใส่ URL / Enter URL", placeholder="www.youtube.com/watch?v=g_9rPvbENUw", lines=1)
                                with gr.Row(scale=1):
                                    url_button_gui = gr.Button("โหลด URL / Process URL", variant="secondary")
                            url_button_gui.click(yt_download_for_ui, [url_media_gui], [local_file, song_title_input])
                        song_input_file = gr.UploadButton('อัปโหลด / Upload 📂', file_types=['audio'], variant='primary', visible=False)
                        show_yt_link_button = gr.Button('วางลิงก์ YouTube/path ไฟล์แทน / Paste link instead', visible=False)
                        song_input_file.upload(process_file_upload, inputs=[song_input_file], outputs=[local_file, song_input, song_title_input])

                    with gr.Column():
                        pitch = gr.Slider(-3, 3, value=0, step=1, label='เปลี่ยนพิทช์ (เฉพาะเสียงร้อง / Vocals ONLY)', info='ปกติใช้ 1 แปลงชาย→หญิง และ -1 หญิง→ชาย (Octaves) / Use 1 for male-to-female, -1 for vice-versa.')
                        pitch_all = gr.Slider(-12, 12, value=0, step=1, label='เปลี่ยนพิทช์รวม / Overall Pitch', info='เปลี่ยนพิทช์/คีย์ทั้งเสียงร้องและดนตรีพร้อมกัน อาจลดคุณภาพเสียงเล็กน้อย (Semitones) / Changes pitch/key of vocals and instrumentals together.')
                        fast_mode = gr.Checkbox(True, label='⚡ โหมดความเร็วสูง / Fast Mode (2x เร็วกว่า)', info='ลดรอบคำนวณแยกเสียงลง 50% (ใช้เวลา ~2-3 นาที) / Halves separation passes for 2x faster conversion')
                    show_file_upload_button.click(swap_visibility, outputs=[file_upload_col, yt_link_col, song_input, local_file])
                    show_yt_link_button.click(swap_visibility, outputs=[yt_link_col, file_upload_col, song_input, local_file])

            with gr.Accordion('ตัวเลือกแปลงเสียง / Voice conversion', open=False):
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

            with gr.Accordion('ตัวเลือกผสมเสียง / Audio mixing', open=False):
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

            with gr.Row():
                clear_btn = gr.ClearButton(value='ล้าง / Clear', components=[song_input, rvc_model, keep_files, local_file, song_title_input, fast_mode])
                generate_btn = gr.Button("สร้างเพลง / Generate", variant='primary')

            with gr.Row():
                with gr.Column(scale=3):
                    ai_cover_audio = gr.Audio(label='เครื่องเล่นเพลง AI / AI Cover Player (กดฟังได้ทันที 🔊)', type='filepath', interactive=False)
                with gr.Column(scale=2):
                    ai_cover_file = gr.File(label="ดาวน์โหลดไฟล์เพลง / Download Audio File 💾", interactive=False)
            clear_btn.add([ai_cover_audio, ai_cover_file])
            gr.Markdown("- You can also try `AICoverGen❤️` in Colab’s free tier, which provides free GPU [link](https://github.com/R3gm/AICoverGen?tab=readme-ov-file#aicovergen).")

            ref_btn.click(update_models_list, None, outputs=rvc_model)
            is_webui = gr.Number(value=1, visible=False)

            def run_cover_webui(*args):
                cover_path = song_cover_pipeline(*args)
                return cover_path, cover_path

            generate_btn.click(run_cover_webui,
                               inputs=[local_file, rvc_model, pitch, keep_files, is_webui, main_gain, backup_gain,
                                       inst_gain, index_rate, filter_radius, rms_mix_rate, f0_method, crepe_hop_length,
                                       protect, pitch_all, reverb_rm_size, reverb_wet, reverb_dry, reverb_damping,
                                       output_format, extra_denoise, steps, song_title_input, fast_mode],
                               outputs=[ai_cover_audio, ai_cover_file])
            clear_btn.click(lambda: [0, 0, 0, 0, 0.5, 3, 0.25, 0.33, 'rmvpe+', 128, 0, 0.15, 0.2, 0.8, 0.7, 'mp3', None, None, True, 1, "", True],
                            outputs=[pitch, main_gain, backup_gain, inst_gain, index_rate, filter_radius, rms_mix_rate,
                                     protect, f0_method, crepe_hop_length, pitch_all, reverb_rm_size, reverb_wet,
                                     reverb_dry, reverb_damping, output_format, ai_cover_audio, ai_cover_file, extra_denoise, steps, song_title_input, fast_mode])

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

    app.launch(
        share=args.share_enabled,
        debug=args.share_enabled,
        show_error=True,
        # enable_queue=True,
        server_name=None if not args.listen else (args.listen_host or '0.0.0.0'),
        server_port=args.listen_port,
        ssr_mode=args.ssr,
        allowed_paths=[output_dir, BASE_DIR]
    )
