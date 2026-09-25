import spaces
import torch
import argparse
import gc
import hashlib
import json
import os
import shlex
import subprocess
from contextlib import suppress
from urllib.parse import urlparse, parse_qs
import time
import shutil

import gradio as gr
import librosa
import numpy as np
import soundfile as sf
import sox
import yt_dlp
from pedalboard import Pedalboard, Reverb, Compressor, HighpassFilter
from pedalboard.io import AudioFile
from pydub import AudioSegment
import noisereduce as nr

from mdx import run_mdx
from rvc import Config, load_hubert, get_vc, rvc_infer
import logging

logging.getLogger("httpx").setLevel(logging.WARNING)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_ZERO_GPU = os.getenv("SPACES_ZERO_GPU")

mdxnet_models_dir = os.path.join(BASE_DIR, 'mdxnet_models')
rvc_models_dir = os.path.join(BASE_DIR, 'rvc_models')
output_dir = os.path.join(BASE_DIR, 'song_output')
downloads_dir = os.path.join(BASE_DIR, 'downloads')


def clean_old_folders(base_path: str, max_age_seconds: int = 10800):
    if not os.path.isdir(base_path):
        print(f"Error: {base_path} is not a valid directory.")
        return

    now = time.time()

    for folder_name in os.listdir(base_path):
        folder_path = os.path.join(base_path, folder_name)
        if os.path.isdir(folder_path):
            last_modified = os.path.getmtime(folder_path)
            if now - last_modified > max_age_seconds:
                # print(f"Deleting folder: {folder_path}")
                shutil.rmtree(folder_path)


def get_youtube_video_id(url, ignore_playlist=True):
    """
    Examples:
    http://youtu.be/SA2iWivDJiE
    http://www.youtube.com/watch?v=_oPAwA_Udwc&feature=feedu
    http://www.youtube.com/embed/SA2iWivDJiE
    http://www.youtube.com/v/SA2iWivDJiE?version=3&amp;hl=en_US
    """
    if "m.youtube.com" in url:
        url = url.replace("m.youtube.com", "www.youtube.com")
    query = urlparse(url)
    if query.hostname == 'youtu.be':
        if query.path[1:] == 'watch':
            return query.query[2:]
        return query.path[1:]

    if query.hostname in {'www.youtube.com', 'youtube.com', 'music.youtube.com'}:
        if not ignore_playlist:
            # use case: get playlist id not current video in playlist
            with suppress(KeyError):
                return parse_qs(query.query)['list'][0]
        if query.path == '/watch':
            return parse_qs(query.query)['v'][0]
        if query.path[:7] == '/watch/':
            return query.path.split('/')[1]
        if query.path[:7] == '/embed/':
            return query.path.split('/')[2]
        if query.path[:3] == '/v/':
            return query.path.split('/')[2]

    # returns None for invalid YouTube url
    return None


def sanitize_filename(name, max_len=150):
    """Make a string safe for Windows filenames. Keeps Unicode (Thai, JP...),
    strips only forbidden chars \\/:*?\"<>| and control chars."""
    import re
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip().rstrip('.')
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or 'song'


def clean_channel_name(channel):
    """Clean promotional suffixes, topic tags, and agency separators from channel/artist names."""
    if not channel:
        return ''
    import re
    import unicodedata
    ch = unicodedata.normalize('NFKC', str(channel))
    # Strip pipe suffix like | WISLIVE, | Warner Music
    ch = re.sub(r'\s*\|\s*.*$', '', ch)
    # Strip topic suffix
    ch = re.sub(r'\s*-\s*Topic$', '', ch, flags=re.IGNORECASE)
    # Strip official, records, channel, vevo
    ch = re.sub(r'\b(?:official(?:\s*(?:channel|music|video|audio))?|vevo|topic|records)\b', '', ch, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', ch).strip(' \t\n\r-_|/')


def clean_song_title(raw_title):
    """Clean common promotional tags and suffixes from video titles
    (e.g., [Official MV], (Official Audio), |Official Lyrics Video|, 【MV】, 4K, HD), normalize Unicode, and sanitize for Windows."""
    import re
    import unicodedata
    if not raw_title:
        return 'song'
    cleaned = unicodedata.normalize('NFKC', str(raw_title))
    noise_patterns = [
        r'\[\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq)\s*\]',
        r'\(\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq)\s*\)',
        r'【\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq)\s*】',
        r'[\(\[\{【]\s*(?:prod\.?|produced)\s*(?:by)?\s*[^)\]\}】]+[\)\]\}】]',
        r'[\s\-_|/]+(?:prod\.?|produced)\s+by\s+[^\-_|/]+',
        r'\|\s*[^|]*(?:official|music|video|audio|m/?v|lyrics?|visualizer)[^|]*\|?',
        r'//\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq).*$',
        r'\b(?:official\s+)?(?:music\s+)?(?:lyrics?\s+video|visualizer)\b.*$',
        r'\b(?:4K|HD|HQ|1080p|720p)\b',
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)

    # Strip decorative opening/closing quote or book brackets around title
    cleaned = re.sub(r'^[《【\[(]\s*', '', cleaned)
    cleaned = re.sub(r'\s*[》】\])]$', '', cleaned)

    cleaned = re.sub(r'[\s\-_|/]+$', '', cleaned)
    cleaned = re.sub(r'^[\s\-_|/]+', '', cleaned)
    return sanitize_filename(cleaned)



_kakasi = None


def get_kakasi():
    """Lazy initializer for pykakasi converter."""
    global _kakasi
    if _kakasi is None:
        try:
            import pykakasi
            _kakasi = pykakasi.kakasi()
        except Exception:
            _kakasi = False
    return _kakasi or None


def romanize_cjk(text):
    """If text contains Japanese (Kanji/Hiragana/Katakana) or Korean (Hangul),
    appends Title-Cased Romaji / Romaja in parentheses: 'Original (Romaji)'.
    Leaves Thai, English, Latin text completely untouched."""
    if not text or not isinstance(text, str):
        return text or ''
    import re
    # 1. Japanese check (Hiragana \u3040-\u309f, Katakana \u30a0-\u30ff, Kanji \u4e00-\u9fff)
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]', text):
        k = get_kakasi()
        if k:
            conv = k.convert(text)
            hepburn = ' '.join(item['hepburn'] for item in conv if item.get('hepburn')).strip()
            hepburn = re.sub(r'\s+', ' ', hepburn).title()
            if hepburn and hepburn.lower() not in text.lower():
                return f"{text} ({hepburn})"

    # 2. Korean check (Hangul \uac00-\ud7a3)
    if re.search(r'[\uac00-\ud7a3]', text):
        try:
            import kroman
            romaja = kroman.parse(text).strip()
            romaja = re.sub(r'\s+', ' ', romaja).title()
            if romaja and romaja.lower() not in text.lower():
                return f"{text} ({romaja})"
        except Exception:
            pass

    return text


def parse_feat_clause(text):
    """Detects and extracts 'feat.', 'ft.', or 'featuring' clause from a title/track string.
    Returns (clean_title, extracted_feat_artist_or_None)."""
    if not text:
        return text, None
    import re
    feat_pattern = r'\s*[\(\[\{]?\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]\}]+)[\)\]\}]?'
    m = re.search(feat_pattern, text, re.IGNORECASE)
    if m:
        feat_artist = m.group(1).strip()
        clean_text = re.sub(feat_pattern, '', text, flags=re.IGNORECASE).strip()
        return clean_text, feat_artist
    return text, None


def resolve_feat_artist(feat_raw, artists_list=None):
    """Resolve clean featured artist name, preferring official metadata romanized name."""
    if artists_list and len(artists_list) > 1:
        return ', '.join(artists_list[1:])
    if not feat_raw:
        return None
    import re
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]', feat_raw):
        k = get_kakasi()
        if k:
            conv = k.convert(feat_raw)
            rom = ' '.join(item['hepburn'] for item in conv if item.get('hepburn')).strip().title()
            if rom:
                return rom
    elif re.search(r'[\uac00-\ud7a3]', feat_raw):
        try:
            import kroman
            rom = kroman.parse(feat_raw).strip().title()
            if rom:
                return rom
        except Exception:
            pass
    return feat_raw


def resolve_artist_name(raw_artist, raw_channel, artists_list=None):
    """Resolve main artist name, romanizing pure CJK script when no Latin representation exists."""
    if artists_list and len(artists_list) > 0:
        candidate = artists_list[0]
    else:
        candidate = raw_artist or raw_channel
    cleaned = clean_channel_name(candidate)
    import re
    if cleaned and not re.search(r'[a-zA-Z]', cleaned):
        if re.search(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]', cleaned):
            k = get_kakasi()
            if k:
                conv = k.convert(cleaned)
                rom = ' '.join(item['hepburn'] for item in conv if item.get('hepburn')).strip().title()
                if rom:
                    return f"{cleaned} ({rom})"
        elif re.search(r'[\uac00-\ud7a3]', cleaned):
            try:
                import kroman
                rom = kroman.parse(cleaned).strip().title()
                if rom:
                    return f"{cleaned} ({rom})"
            except Exception:
                pass
    return cleaned


def extract_song_and_artist(info):
    """Extract and format '[Artist] - [Song] ([Romaji]) Feat. [Featured Artist]' from yt-dlp metadata info dict."""
    if not isinstance(info, dict):
        return clean_song_title(str(info))

    import re
    import unicodedata

    raw_title = info.get('title') or info.get('fulltitle') or info.get('id') or 'song'
    raw_track = info.get('track')
    raw_artist = info.get('artist')
    raw_channel = info.get('channel') or info.get('uploader')
    artists_list = info.get('artists') or []

    # 1. Official YouTube Music track (has dedicated track and artist fields)
    if raw_track and raw_artist:
        base_track, feat_in_track = parse_feat_clause(raw_track)
        clean_track = clean_song_title(base_track)
        song_with_romaji = romanize_cjk(clean_track)
        main_artist = resolve_artist_name(raw_artist, raw_channel, artists_list)

        feat_artist = None
        if feat_in_track:
            feat_artist = resolve_feat_artist(feat_in_track, artists_list)

        if feat_artist:
            return sanitize_filename(f"{main_artist} - {song_with_romaji} Feat. {feat_artist}")
        elif main_artist:
            return sanitize_filename(f"{main_artist} - {song_with_romaji}")
        return sanitize_filename(song_with_romaji)

    title_norm = unicodedata.normalize('NFKC', str(raw_title))
    clean_title = clean_song_title(title_norm)

    # 2. Check for 'Song by Artist' pattern (e.g. 《 เพลงรัก 》 by Liz's x NATNON)
    # Only evaluate if title does not already have an explicit ' - ' separator
    if ' - ' not in clean_title:
        by_match = re.match(r'^[《【\[(]?\s*(.*?)\s*[》】\])]?\s+(?:by|โดย)\s+(.+)$', clean_title, re.IGNORECASE)
        if by_match:
            base_song, feat_in_song = parse_feat_clause(by_match.group(1))
            song = clean_song_title(base_song)
            song_with_romaji = romanize_cjk(song)
            artist = resolve_artist_name(by_match.group(2), raw_channel, artists_list)
            if feat_in_song:
                feat_artist = resolve_feat_artist(feat_in_song, artists_list)
                return sanitize_filename(f"{artist} - {song_with_romaji} Feat. {feat_artist}")
            if artist:
                return sanitize_filename(f"{artist} - {song_with_romaji}")
            return sanitize_filename(song_with_romaji)

    # 3. If title already has ' - ' (Artist - Song or Song - Artist)
    if ' - ' in clean_title:
        part1, part2 = clean_title.split(' - ', 1)
        part1 = part1.strip()
        part2 = part2.strip()

        # Inversion detection: check if uploader formatted as 'Song - Artist'
        ch = clean_channel_name(raw_artist or raw_channel)
        if ch and ch.lower() in part2.lower() and ch.lower() not in part1.lower():
            # Inversion detected: part2 is artist, part1 is song
            artist_raw = part2
            song_raw = part1
        else:
            artist_raw = part1
            song_raw = part2

        base_song, feat_in_song = parse_feat_clause(song_raw)
        base_artist, feat_in_artist = parse_feat_clause(artist_raw)
        feat_candidate = feat_in_song or feat_in_artist

        clean_song = clean_song_title(base_song)
        song_with_romaji = romanize_cjk(clean_song)
        main_artist = resolve_artist_name(base_artist, raw_channel, artists_list)

        if feat_candidate:
            feat_artist = resolve_feat_artist(feat_candidate, artists_list)
            return sanitize_filename(f"{main_artist} - {song_with_romaji} Feat. {feat_artist}")
        return sanitize_filename(f"{main_artist} - {song_with_romaji}")


    # 4. Fallback to channel/artist if not already in title
    base_title, feat_in_title = parse_feat_clause(clean_title)
    clean_title = clean_song_title(base_title)
    song_with_romaji = romanize_cjk(clean_title)
    artist_candidate = resolve_artist_name(raw_artist, raw_channel, artists_list)

    feat_artist = None
    if feat_in_title:
        feat_artist = resolve_feat_artist(feat_in_title, artists_list)

    if artist_candidate and artist_candidate.lower() not in song_with_romaji.lower():
        if feat_artist:
            return sanitize_filename(f"{artist_candidate} - {song_with_romaji} Feat. {feat_artist}")
        return sanitize_filename(f"{artist_candidate} - {song_with_romaji}")

    if feat_artist:
        return sanitize_filename(f"{song_with_romaji} Feat. {feat_artist}")
    return sanitize_filename(song_with_romaji)



def yt_download(link):
    if not link.strip():
        gr.Info("You need to provide a download link.")
        return None, None
    os.makedirs(downloads_dir, exist_ok=True)
    ydl_opts = {
        'format': 'bestaudio',
        'outtmpl': os.path.join(downloads_dir, '%(id)s'),
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'no_warnings': True,
        'quiet': True,
        'noprogress': True,
        'extractaudio': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(link, download=True)
        raw_path = ydl.prepare_filename(result, outtmpl=os.path.join(downloads_dir, '%(id)s.mp3'))
        song_title = extract_song_and_artist(result)

    # Rename downloaded file directly to the clean song title so UI and file box show the real song title
    target_dir = downloads_dir
    target_path = os.path.join(target_dir, f"{song_title}.mp3")
    try:
        if os.path.abspath(raw_path) != os.path.abspath(target_path):
            if os.path.exists(target_path):
                os.remove(target_path)
            os.rename(raw_path, target_path)
        download_path = target_path
    except Exception as e:
        print(f"[*] Notice: Could not rename {raw_path} to {target_path}: {e}", flush=True)
        download_path = raw_path

    # Save sidecar metadata so local reading of this file can also recover the clean song title
    try:
        sidecar_path = os.path.splitext(download_path)[0] + '.title'
        with open(sidecar_path, 'w', encoding='utf-8') as f:
            f.write(song_title)
    except Exception:
        pass

    return download_path, song_title


def ensure_ascii_audio_path(audio_path, song_id):
    """libsndfile on Windows cannot open non-ASCII filenames (Thai, CJK, emoji...).
    Copy to an ASCII-safe name inside song_output if needed. Returns (path, temp_copy_or_None)."""
    basename = os.path.basename(audio_path)
    try:
        basename.encode('ascii')
        return audio_path, None
    except UnicodeEncodeError:
        pass
    ext = os.path.splitext(basename)[1] or '.wav'
    safe_dir = os.path.join(output_dir, song_id)
    os.makedirs(safe_dir, exist_ok=True)
    safe_path = os.path.join(safe_dir, f"song_{song_id}{ext}")
    shutil.copy2(audio_path, safe_path)
    print(f"[*] Non-ASCII filename detected, using safe copy: {safe_path}", flush=True)
    return safe_path, safe_path


def raise_exception(error_msg, is_webui):
    if is_webui:
        raise gr.Error(error_msg)
    else:
        raise Exception(error_msg)


def get_rvc_model(voice_model, is_webui):
    rvc_model_filename, rvc_index_filename = None, None
    model_dir = os.path.join(rvc_models_dir, voice_model)
    # print(model_dir)
    for file in os.listdir(model_dir):
        # print(file)
        if os.path.isdir(file):
            for ff in os.listdir(file):
                # print("subfile", ff)
                ext = os.path.splitext(ff)[1]
                if ext == '.pth':
                    rvc_model_filename = ff
                if ext == '.index':
                    rvc_index_filename = ff
        ext = os.path.splitext(file)[1]
        if ext == '.pth':
            rvc_model_filename = file
        if ext == '.index':
            rvc_index_filename = file

    if rvc_model_filename is None:
        error_msg = f'No model file exists in {model_dir}.'
        raise_exception(error_msg, is_webui)

    return os.path.join(model_dir, rvc_model_filename), os.path.join(model_dir, rvc_index_filename) if rvc_index_filename else ''


def get_audio_paths(song_dir):
    orig_song_path = None
    instrumentals_path = None
    main_vocals_dereverb_path = None
    backup_vocals_path = None

    for file in os.listdir(song_dir):
        if file.endswith('_Instrumental.wav'):
            instrumentals_path = os.path.join(song_dir, file)
            orig_song_path = instrumentals_path.replace('_Instrumental', '')

        elif file.endswith('_Vocals_Main_DeReverb.wav'):
            main_vocals_dereverb_path = os.path.join(song_dir, file)

        elif file.endswith('_Vocals_Backup.wav'):
            backup_vocals_path = os.path.join(song_dir, file)

    # print(orig_song_path, instrumentals_path, main_vocals_dereverb_path, backup_vocals_path)
    return orig_song_path, instrumentals_path, main_vocals_dereverb_path, backup_vocals_path


def get_audio_with_suffix(song_dir, suffix="_mysuffix.wav"):
    target_path = None

    for file in os.listdir(song_dir):
        if file.endswith(suffix):
            target_path = os.path.join(song_dir, file)
            break

    return target_path


def convert_to_stereo(audio_path):
    wave, sr = librosa.load(audio_path, mono=False, sr=44100)

    # check if mono
    if type(wave[0]) != np.ndarray:
        stereo_path = f'{os.path.splitext(audio_path)[0]}_stereo.wav'
        command = shlex.split(f'ffmpeg -y -loglevel error -i "{audio_path}" -ac 2 -f wav "{stereo_path}"')
        subprocess.run(command)
        return stereo_path
    else:
        return audio_path


def pitch_shift(audio_path, pitch_change):
    output_path = f'{os.path.splitext(audio_path)[0]}_p{pitch_change}.wav'
    if not os.path.exists(output_path):
        tfm = sox.Transformer()
        tfm.pitch(pitch_change)
        try:
            # Direct file transformation: avoids Windows CRT stdout pipe byte alignment errors
            tfm.build_file(input_filepath=audio_path, output_filepath=output_path)
        except Exception:
            # Fallback to in-memory array processing
            y, sr = sf.read(audio_path)
            y_shifted = tfm.build_array(input_array=y, sample_rate_in=sr)
            sf.write(output_path, y_shifted, sr)

    return output_path


def get_hash(filepath):
    with open(filepath, 'rb') as f:
        file_hash = hashlib.blake2b()
        while chunk := f.read(8192):
            file_hash.update(chunk)

    return file_hash.hexdigest()[:11]


_progress_times = {}


def display_progress(message, percent, is_webui, progress=None):
    import datetime
    now = time.time()
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    suffix = ""
    last_key = "_last"
    if last_key in _progress_times:
        last_time, last_msg = _progress_times[last_key]
        elapsed = now - last_time
        mins, secs = divmod(int(elapsed), 60)
        if mins > 0:
            suffix = f" [+{mins}m {secs}s]"
        else:
            suffix = f" [+{secs}s]"
    _progress_times[last_key] = (now, message)
    print(f"[{now_str}] {message}{suffix}", flush=True)
    if is_webui and progress is not None:
        progress(percent, desc=message)


def preprocess_song(song_input, mdx_model_params, song_id, is_webui, input_type, progress, keep_orig, orig_song_path, fast_mode=True):

    song_output_dir = os.path.join(output_dir, song_id)
    do_denoise = not fast_mode

    display_progress('[~] Separating Vocals from Instrumental...', 0.1, is_webui, progress)
    vocals_path, instrumentals_path = run_mdx(mdx_model_params, song_output_dir, os.path.join(mdxnet_models_dir, 'UVR-MDX-NET-Voc_FT.onnx'), orig_song_path, denoise=do_denoise, keep_orig=keep_orig)

    display_progress('[~] Separating Main Vocals from Backup Vocals...', 0.2, is_webui, progress)
    backup_vocals_path, main_vocals_path = run_mdx(mdx_model_params, song_output_dir, os.path.join(mdxnet_models_dir, 'UVR_MDXNET_KARA_2.onnx'), vocals_path, suffix='Backup', invert_suffix='Main', denoise=do_denoise)

    display_progress('[~] Applying DeReverb to Vocals...', 0.3, is_webui, progress)
    _, main_vocals_dereverb_path = run_mdx(mdx_model_params, song_output_dir, os.path.join(mdxnet_models_dir, 'Reverb_HQ_By_FoxJoy.onnx'), main_vocals_path, invert_suffix='DeReverb', exclude_main=True, denoise=do_denoise)

    return orig_song_path, vocals_path, instrumentals_path, main_vocals_path, backup_vocals_path, main_vocals_dereverb_path


def get_audio_file(song_input, is_webui, input_type, progress):
    keep_orig = False
    song_title = None
    if input_type == 'yt':
        display_progress('[~] Downloading song...', 0, is_webui, progress)
        song_link = song_input.split('&')[0]
        orig_song_path, song_title = yt_download(song_link)
    elif input_type == 'local':
        orig_song_path = song_input
        sidecar_path = os.path.splitext(song_input)[0] + '.title'
        if os.path.exists(sidecar_path):
            try:
                with open(sidecar_path, 'r', encoding='utf-8') as f:
                    song_title = f.read().strip()
            except Exception:
                pass
        if not song_title:
            song_title = clean_song_title(os.path.splitext(os.path.basename(song_input))[0])
        keep_orig = True
    else:
        orig_song_path = None
    return keep_orig, orig_song_path, song_title

device = "cuda:0" if torch.cuda.is_available() else "cpu"
compute_half = True if torch.cuda.is_available() else False
config = Config(device, compute_half)
hubert_model = load_hubert("cuda", config.is_half, os.path.join(rvc_models_dir, 'hubert_base.pt'))
print(device, "half>>", config.is_half)

# @spaces.GPU(enable_queue=True)
def voice_change(voice_model, vocals_path, output_path, pitch_change, f0_method, index_rate, filter_radius, rms_mix_rate, protect, crepe_hop_length, is_webui, steps):
    rvc_model_path, rvc_index_path = get_rvc_model(voice_model, is_webui)

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    compute_half = True if torch.cuda.is_available() else False
    config = Config(device, compute_half)

    cpt, version, net_g, tgt_sr, vc = get_vc(device, config.is_half, config, rvc_model_path)

    # convert main vocals
    global hubert_model
    rvc_infer(rvc_index_path, index_rate, vocals_path, output_path, pitch_change, f0_method, cpt, version, net_g, filter_radius, tgt_sr, rms_mix_rate, protect, crepe_hop_length, vc, hubert_model, steps)
    del cpt
    gc.collect()


def add_audio_effects(audio_path, reverb_rm_size, reverb_wet, reverb_dry, reverb_damping):
    output_path = f'{os.path.splitext(audio_path)[0]}_mixed.wav'

    # Initialize audio effects plugins
    board = Pedalboard(
        [
            HighpassFilter(),
            Compressor(ratio=4, threshold_db=-15),
            Reverb(room_size=reverb_rm_size, dry_level=reverb_dry, wet_level=reverb_wet, damping=reverb_damping)
         ]
    )

    with AudioFile(audio_path) as f:
        with AudioFile(output_path, 'w', f.samplerate, f.num_channels) as o:
            # Read one second of audio at a time, until the file is empty:
            while f.tell() < f.frames:
                chunk = f.read(int(f.samplerate))
                effected = board(chunk, f.samplerate, reset=False)
                o.write(effected)

    return output_path


def combine_audio(audio_paths, output_path, main_gain, backup_gain, inst_gain, output_format):
    main_vocal_audio = AudioSegment.from_wav(audio_paths[0]) - 4 + main_gain
    backup_vocal_audio = AudioSegment.from_wav(audio_paths[1]) - 6 + backup_gain
    instrumental_audio = AudioSegment.from_wav(audio_paths[2]) - 7 + inst_gain
    main_vocal_audio.overlay(backup_vocal_audio).overlay(instrumental_audio).export(output_path, format=output_format)


# @spaces.GPU(enable_queue=True, duration=130)
@spaces.GPU(duration=59)
def process_song(
    song_dir, song_input, mdx_model_params, song_id, is_webui, input_type, progress,
    keep_files, pitch_change, pitch_change_all, voice_model, index_rate, filter_radius,
    rms_mix_rate, protect, f0_method, crepe_hop_length, output_format, keep_orig, orig_song_path, steps,
    song_title=None, fast_mode=True
):

    if not os.path.exists(song_dir):
        os.makedirs(song_dir)
        orig_song_path, vocals_path, instrumentals_path, main_vocals_path, backup_vocals_path, main_vocals_dereverb_path = preprocess_song(song_input, mdx_model_params, song_id, is_webui, input_type, progress, keep_orig, orig_song_path, fast_mode=fast_mode)
    else:
        vocals_path, main_vocals_path = None, None
        paths = get_audio_paths(song_dir)

        # if any of the audio files aren't available or keep intermediate files, rerun preprocess
        if any(path is None for path in paths):
            orig_song_path, vocals_path, instrumentals_path, main_vocals_path, backup_vocals_path, main_vocals_dereverb_path = preprocess_song(song_input, mdx_model_params, song_id, is_webui, input_type, progress, keep_orig, orig_song_path, fast_mode=fast_mode)
        else:
            orig_song_path, instrumentals_path, main_vocals_dereverb_path, backup_vocals_path = paths

    pitch_change = pitch_change * 12 + pitch_change_all
    # intermediate vocals file stays ASCII-safe (libsndfile/RVC can't read non-ASCII on Windows)
    safe_stem = os.path.splitext(os.path.basename(orig_song_path))[0]
    # final cover uses the original song title: "<Title> (<VoiceModel> Ver).mp3"
    cover_stem = song_title or safe_stem
    ai_vocals_path = os.path.join(song_dir, f'{safe_stem}_{voice_model}_p{pitch_change}_i{index_rate}_fr{filter_radius}_rms{rms_mix_rate}_pro{protect}_{f0_method}{"" if f0_method != "mangio-crepe" else f"_{crepe_hop_length}"}_s{steps}.wav')
    ai_cover_path = os.path.join(song_dir, f'{cover_stem} ({voice_model} Ver).{output_format}')

    if not os.path.exists(ai_vocals_path):
        display_progress('[~] Converting voice using RVC...', 0.5, is_webui, progress)
        voice_change(voice_model, main_vocals_dereverb_path, ai_vocals_path, pitch_change, f0_method, index_rate, filter_radius, rms_mix_rate, protect, crepe_hop_length, is_webui, steps)

    return ai_vocals_path, ai_cover_path, instrumentals_path, backup_vocals_path, vocals_path, main_vocals_path


def apply_noisereduce(audio_list, type_output="wav"):
    # https://github.com/sa-if/Audio-Denoiser
    print("Noise reduce")

    result = []
    for audio_path in audio_list:
        out_path = f"{os.path.splitext(audio_path)[0]}_nr.{type_output}"

        try:
            # Load audio file
            audio = AudioSegment.from_file(audio_path)

            # Convert audio to numpy array
            samples = np.array(audio.get_array_of_samples())

            # Reduce noise
            reduced_noise = nr.reduce_noise(samples, sr=audio.frame_rate, prop_decrease=0.6)

            # Convert reduced noise signal back to audio
            reduced_audio = AudioSegment(
                reduced_noise.tobytes(), 
                frame_rate=audio.frame_rate, 
                sample_width=audio.sample_width,
                channels=audio.channels
            )

            # Save reduced audio to file
            reduced_audio.export(out_path, format=type_output)
            result.append(out_path)

        except Exception as e:
            print(f"Error noisereduce: {str(e)}")
            result.append(audio_path)

    return result


# @spaces.GPU(duration=140)
def song_cover_pipeline(song_input, voice_model, pitch_change, keep_files,
                        is_webui=0, main_gain=0, backup_gain=0, inst_gain=0, index_rate=0.5, filter_radius=3,
                        rms_mix_rate=0.25, f0_method='rmvpe', crepe_hop_length=128, protect=0.33, pitch_change_all=0,
                        reverb_rm_size=0.15, reverb_wet=0.2, reverb_dry=0.8, reverb_damping=0.7, output_format='mp3',
                        extra_denoise=False, steps=1, song_title=None, fast_mode=True,
                        progress=gr.Progress()):
    if not keep_files or IS_ZERO_GPU:
        clean_old_folders("./song_output", 14400)

    if IS_ZERO_GPU:
        clean_old_folders("./rvc_models", 10800)

    try:
        pipeline_start = time.time()
        if not song_input or not voice_model:
            raise_exception('Ensure that the song input field and voice model field is filled.', is_webui)

        display_progress('[~] Starting AI Cover Generation Pipeline...', 0, is_webui, progress)

        with open(os.path.join(mdxnet_models_dir, 'model_data.json')) as infile:
            mdx_model_params = json.load(infile)

        # if youtube url
        if urlparse(song_input).scheme == 'https':
            input_type = 'yt'
            song_id = get_youtube_video_id(song_input)
            if song_id is None:
                error_msg = 'Invalid YouTube url.'
                raise_exception(error_msg, is_webui)

        # local audio file
        else:
            input_type = 'local'
            song_input = song_input.strip('\"')
            if os.path.exists(song_input):
                song_id = get_hash(song_input)
            else:
                error_msg = f'{song_input} does not exist.'
                song_id = None
                raise_exception(error_msg, is_webui)

        song_dir = os.path.join(output_dir, song_id)

        keep_orig, orig_song_path, detected_song_title = get_audio_file(song_input, is_webui, input_type, progress)
        if song_title and isinstance(song_title, str) and song_title.strip():
            effective_song_title = clean_song_title(song_title.strip())
        else:
            effective_song_title = detected_song_title

        orig_song_path, ascii_temp_copy = ensure_ascii_audio_path(orig_song_path, song_id)
        orig_song_path = convert_to_stereo(orig_song_path)

        start = time.time()

        (
            ai_vocals_path,
            ai_cover_path,
            instrumentals_path,
            backup_vocals_path,
            vocals_path,
            main_vocals_path
        ) = process_song(
            song_dir,
            song_input,
            mdx_model_params,
            song_id,
            is_webui,
            input_type,
            progress,
            keep_files,
            pitch_change,
            pitch_change_all,
            voice_model,
            index_rate,
            filter_radius,
            rms_mix_rate,
            protect,
            f0_method,
            crepe_hop_length,
            output_format,
            keep_orig,
            orig_song_path,
            steps,
            effective_song_title,
            fast_mode=fast_mode,
        )

        end = time.time()
        print(f"Execution time: {end - start:.4f} seconds")
        with sf.SoundFile(ai_vocals_path) as f:
            duration__ = len(f) / f.samplerate
        print(f"Audio duration: {duration__:.2f} seconds")

        display_progress('[~] Applying audio effects to Vocals...', 0.8, is_webui, progress)

        nr_path = ai_vocals_path  # get_audio_with_suffix(song_dir, "_nr.wav")
        if extra_denoise:
            ai_vocals_path = apply_noisereduce([ai_vocals_path])[0]

        ai_vocals_mixed_path = add_audio_effects(ai_vocals_path, reverb_rm_size, reverb_wet, reverb_dry, reverb_damping)

        ins_path = get_audio_with_suffix(song_dir, "_Voiceless.wav")
        if not ins_path:
            instrumentals_path, _ = run_mdx(
                mdx_model_params,
                os.path.join(output_dir, song_id),
                os.path.join(mdxnet_models_dir, "UVR-MDX-NET-Inst_HQ_4.onnx"),
                instrumentals_path,
                # exclude_main=False,
                exclude_inversion=True,
                suffix="Voiceless",
                denoise=False,
                keep_orig=True,
                base_device=("" if IS_ZERO_GPU else "cuda")
            )
        
        if pitch_change_all != 0:
            display_progress('[~] Applying overall pitch change', 0.85, is_webui, progress)
            instrumentals_path = pitch_shift(instrumentals_path, pitch_change_all)
            backup_vocals_path = pitch_shift(backup_vocals_path, pitch_change_all)

        display_progress('[~] Combining AI Vocals and Instrumentals...', 0.9, is_webui, progress)
        combine_audio([ai_vocals_mixed_path, backup_vocals_path, instrumentals_path], ai_cover_path, main_gain, backup_gain, inst_gain, output_format)

        if not keep_files:
            display_progress('[~] Removing intermediate audio files...', 0.95, is_webui, progress)
            intermediate_files = [vocals_path, main_vocals_path, ai_vocals_mixed_path, ins_path, nr_path, ascii_temp_copy]
            if pitch_change_all != 0:
                intermediate_files += [instrumentals_path, backup_vocals_path]
            for file in intermediate_files:
                if file and os.path.exists(file):
                    os.remove(file)

        pipeline_end = time.time()
        pipeline_elapsed = pipeline_end - pipeline_start
        mins, secs = divmod(int(pipeline_elapsed), 60)
        if mins > 0:
            total_str = f"{mins}m {secs}s"
        else:
            total_str = f"{secs}s"
        print(f"[+] Total time all process: {total_str} ({pipeline_elapsed:.1f}s)", flush=True)

        return ai_cover_path

    except Exception as e:
        raise_exception(str(e), is_webui)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a AI cover song in the song_output/id directory.', add_help=True)
    parser.add_argument('-i', '--song-input', type=str, required=True, help='Link to a YouTube video or the filepath to a local mp3/wav file to create an AI cover of')
    parser.add_argument('-dir', '--rvc-dirname', type=str, required=True, help='Name of the folder in the rvc_models directory containing the RVC model file and optional index file to use')
    parser.add_argument('-p', '--pitch-change', type=int, required=True, help='Change the pitch of AI Vocals only. Generally, use 1 for male to female and -1 for vice-versa. (Octaves)')
    parser.add_argument('-k', '--keep-files', action=argparse.BooleanOptionalAction, help='Whether to keep all intermediate audio files generated in the song_output/id directory, e.g. Isolated Vocals/Instrumentals')
    parser.add_argument('-ir', '--index-rate', type=float, default=0.5, help='A decimal number e.g. 0.5, used to reduce/resolve the timbre leakage problem. If set to 1, more biased towards the timbre quality of the training dataset')
    parser.add_argument('-fr', '--filter-radius', type=int, default=3, help='A number between 0 and 7. If >=3: apply median filtering to the harvested pitch results. The value represents the filter radius and can reduce breathiness.')
    parser.add_argument('-rms', '--rms-mix-rate', type=float, default=0.25, help="A decimal number e.g. 0.25. Control how much to use the original vocal's loudness (0) or a fixed loudness (1).")
    parser.add_argument('-palgo', '--pitch-detection-algo', type=str, default='rmvpe', help='Best option is rmvpe (clarity in vocals), then mangio-crepe (smoother vocals).')
    parser.add_argument('-hop', '--crepe-hop-length', type=int, default=128, help='If pitch detection algo is mangio-crepe, controls how often it checks for pitch changes in milliseconds. The higher the value, the faster the conversion and less risk of voice cracks, but there is less pitch accuracy. Recommended: 128.')
    parser.add_argument('-pro', '--protect', type=float, default=0.33, help='A decimal number e.g. 0.33. Protect voiceless consonants and breath sounds to prevent artifacts such as tearing in electronic music. Set to 0.5 to disable. Decrease the value to increase protection, but it may reduce indexing accuracy.')
    parser.add_argument('-mv', '--main-vol', type=int, default=0, help='Volume change for AI main vocals in decibels. Use -3 to decrease by 3 decibels and 3 to increase by 3 decibels')
    parser.add_argument('-bv', '--backup-vol', type=int, default=0, help='Volume change for backup vocals in decibels')
    parser.add_argument('-iv', '--inst-vol', type=int, default=0, help='Volume change for instrumentals in decibels')
    parser.add_argument('-pall', '--pitch-change-all', type=int, default=0, help='Change the pitch/key of vocals and instrumentals. Changing this slightly reduces sound quality')
    parser.add_argument('-rsize', '--reverb-size', type=float, default=0.15, help='Reverb room size between 0 and 1')
    parser.add_argument('-rwet', '--reverb-wetness', type=float, default=0.2, help='Reverb wet level between 0 and 1')
    parser.add_argument('-rdry', '--reverb-dryness', type=float, default=0.8, help='Reverb dry level between 0 and 1')
    parser.add_argument('-rdamp', '--reverb-damping', type=float, default=0.7, help='Reverb damping between 0 and 1')
    parser.add_argument('-oformat', '--output-format', type=str, default='mp3', help='Output format of audio file. mp3 for smaller file size, wav for best quality')
    parser.add_argument('-st', '--song-title', type=str, default=None, help='Custom title of the song for naming output cover file')
    args = parser.parse_args()

    rvc_dirname = args.rvc_dirname
    if not os.path.exists(os.path.join(rvc_models_dir, rvc_dirname)):
        raise Exception(f'The folder {os.path.join(rvc_models_dir, rvc_dirname)} does not exist.')

    cover_path = song_cover_pipeline(args.song_input, rvc_dirname, args.pitch_change, args.keep_files,
                                     main_gain=args.main_vol, backup_gain=args.backup_vol, inst_gain=args.inst_vol,
                                     index_rate=args.index_rate, filter_radius=args.filter_radius,
                                     rms_mix_rate=args.rms_mix_rate, f0_method=args.pitch_detection_algo,
                                     crepe_hop_length=args.crepe_hop_length, protect=args.protect,
                                     pitch_change_all=args.pitch_change_all,
                                     reverb_rm_size=args.reverb_size, reverb_wet=args.reverb_wetness,
                                     reverb_dry=args.reverb_dryness, reverb_damping=args.reverb_damping,
                                     output_format=args.output_format,
                                     song_title=args.song_title)
    print(f'[+] Cover generated at {cover_path}')