"""
Video producer for RoarRhythm.
Produces landscape main video + 2 portrait shorts.
No Google Drive dependency — works standalone in GitHub Actions.
"""

import os
import subprocess
import requests
import glob
from pathlib import Path

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
PIXABAY_KEY = os.environ.get('PIXABAY_KEY', '')
PEXELS_KEY = os.environ.get('PEXELS_KEY', '')
FONT_PATH = '/tmp/Montserrat-Bold.ttf'
WORK_DIR = Path('/tmp/roarrhythm')


def setup():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    # Install font
    if not Path(FONT_PATH).exists():
        r = requests.get(
            'https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf',
            headers=HEADERS, timeout=30
        )
        Path(FONT_PATH).write_bytes(r.content)
    print("Setup complete")


def run_ffmpeg(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FFmpeg error: {r.stderr[-400:]}")
        raise RuntimeError("FFmpeg failed")
    return r


def get_duration(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', str(path)],
        capture_output=True, text=True
    )
    return float(r.stdout.strip() or 0)


def download_music(music_url):
    music_path = WORK_DIR / 'music.mp3'
    if music_path.exists() and get_duration(music_path) > 30:
        return str(music_path)
    print("Downloading music...")
    try:
        result = subprocess.run(
            ['yt-dlp', '-x', '--audio-format', 'mp3', '--audio-quality', '0',
             '-o', str(WORK_DIR / 'music.%(ext)s'), '--no-playlist', music_url],
            capture_output=True, text=True, timeout=120
        )
        if music_path.exists():
            print(f"Music downloaded: {get_duration(music_path):.1f}s")
            return str(music_path)
    except Exception as e:
        print(f"yt-dlp failed: {e}")
    # CDN fallback
    from topics import MUSIC_FALLBACK_URLS
    for url in MUSIC_FALLBACK_URLS:
        try:
            r = requests.get(url, stream=True, headers=HEADERS, timeout=60)
            r.raise_for_status()
            with open(music_path, 'wb') as f:
                for chunk in r.iter_content(16384):
                    f.write(chunk)
            if get_duration(music_path) > 30:
                print(f"Music from CDN: {get_duration(music_path):.1f}s")
                return str(music_path)
        except Exception:
            continue
    raise RuntimeError("Could not download music")


# ─── PIXABAY ────────────────────────────────────────────────────────────────

def search_pixabay(queries, min_width=1280):
    all_hits = []
    for q in queries:
        try:
            resp = requests.get(
                'https://pixabay.com/api/videos/',
                params={'key': PIXABAY_KEY, 'q': q, 'min_width': min_width,
                        'per_page': 20, 'order': 'popular', 'safesearch': 'true'},
                timeout=30
            )
            all_hits.extend(resp.json().get('hits', []))
        except Exception as e:
            print(f"Pixabay search error for '{q}': {e}")

    seen = set()
    clips = []
    for hit in all_hits:
        if hit['id'] in seen or hit['duration'] < 6:
            continue
        seen.add(hit['id'])
        for quality in ['large', 'medium', 'small']:
            v = hit.get('videos', {}).get(quality, {})
            w = v.get('width', 0)
            h = v.get('height', 1)
            if v.get('url') and w >= min_width and (w / h) >= 1.5:
                clips.append({'url': v['url'], 'dur': hit['duration'],
                              'id': hit['id'], 'w': w, 'h': h, 'source': 'pixabay'})
                break
    return clips


# ─── PEXELS ─────────────────────────────────────────────────────────────────

def search_pexels_landscape(queries):
    clips = []
    for q in queries:
        try:
            resp = requests.get(
                'https://api.pexels.com/videos/search',
                headers={'Authorization': PEXELS_KEY},
                params={'query': q, 'orientation': 'landscape',
                        'per_page': 15, 'min_duration': 6},
                timeout=30
            )
            for v in resp.json().get('videos', []):
                if v.get('duration', 0) < 6:
                    continue
                # Pick best file
                files = sorted(
                    [f for f in v.get('video_files', [])
                     if f.get('width', 0) >= 1280 and f.get('file_type') == 'video/mp4'],
                    key=lambda x: x.get('width', 0), reverse=True
                )
                if files:
                    f = files[0]
                    w = f.get('width', 0)
                    h = f.get('height', 1)
                    if (w / h) >= 1.5:
                        clips.append({'url': f['link'], 'dur': v['duration'],
                                      'id': v['id'], 'w': w, 'h': h, 'source': 'pexels'})
        except Exception as e:
            print(f"Pexels landscape error for '{q}': {e}")
    return clips


def search_pexels_portrait(queries):
    clips = []
    for q in queries:
        try:
            resp = requests.get(
                'https://api.pexels.com/videos/search',
                headers={'Authorization': PEXELS_KEY},
                params={'query': q, 'orientation': 'portrait',
                        'per_page': 15, 'min_duration': 5},
                timeout=30
            )
            for v in resp.json().get('videos', []):
                if v.get('duration', 0) < 5:
                    continue
                files = sorted(
                    [f for f in v.get('video_files', [])
                     if f.get('height', 0) >= 1080 and f.get('file_type') == 'video/mp4'],
                    key=lambda x: x.get('height', 0), reverse=True
                )
                if files:
                    f = files[0]
                    clips.append({'url': f['link'], 'dur': v['duration'],
                                  'id': v['id'], 'w': f.get('width', 0),
                                  'h': f.get('height', 0), 'source': 'pexels_portrait'})
        except Exception as e:
            print(f"Pexels portrait error for '{q}': {e}")
    return clips


# ─── NORMALIZATION ───────────────────────────────────────────────────────────

def normalize_landscape(clips, max_clips=12, trim=12):
    """Download and normalize clips to 1920x1080 landscape, audio stripped."""
    norm_paths = []
    selected = clips[:max_clips]
    for i, clip in enumerate(selected):
        norm = WORK_DIR / f'norm_l_{i:02d}.mp4'
        if norm.exists() and get_duration(norm) > 1:
            norm_paths.append((str(norm), get_duration(norm)))
            print(f"  [L{i+1:02d}] cached")
            continue
        raw = WORK_DIR / f'raw_l_{i:02d}.mp4'
        print(f"  [L{i+1:02d}] DL {clip['id']} ({clip['source']})...", end=' ', flush=True)
        try:
            r = requests.get(clip['url'], stream=True, headers=HEADERS, timeout=90)
            r.raise_for_status()
            with open(raw, 'wb') as f:
                for chunk in r.iter_content(16384):
                    f.write(chunk)
            real_dur = get_duration(raw)
            trim_dur = min(real_dur, trim)
            print(f"{real_dur:.0f}s->{trim_dur:.0f}s", end=' ', flush=True)
            run_ffmpeg(
                f'ffmpeg -y -i "{raw}" '
                f'-vf "scale=1920:1080:force_original_aspect_ratio=increase,'
                f'crop=1920:1080,setsar=1" '
                f'-t {trim_dur:.3f} -r 30 -c:v libx264 -preset fast -crf 22 -an '
                f'"{norm}" -loglevel error'
            )
            raw.unlink(missing_ok=True)
            d = get_duration(norm)
            norm_paths.append((str(norm), d))
            print(f"ok ({d:.1f}s)")
        except Exception as e:
            print(f"SKIP: {e}")
            raw.unlink(missing_ok=True)
    return norm_paths


def normalize_portrait(clips, max_clips=8, trim=12):
    """Download and normalize clips to 1080x1920 portrait, audio stripped."""
    norm_paths = []
    selected = clips[:max_clips]
    for i, clip in enumerate(selected):
        norm = WORK_DIR / f'norm_p_{i:02d}.mp4'
        if norm.exists() and get_duration(norm) > 1:
            norm_paths.append((str(norm), get_duration(norm)))
            print(f"  [P{i+1:02d}] cached")
            continue
        raw = WORK_DIR / f'raw_p_{i:02d}.mp4'
        print(f"  [P{i+1:02d}] DL {clip['id']} ({clip['source']})...", end=' ', flush=True)
        try:
            r = requests.get(clip['url'], stream=True, headers=HEADERS, timeout=90)
            r.raise_for_status()
            with open(raw, 'wb') as f:
                for chunk in r.iter_content(16384):
                    f.write(chunk)
            real_dur = get_duration(raw)
            trim_dur = min(real_dur, trim)
            print(f"{real_dur:.0f}s->{trim_dur:.0f}s", end=' ', flush=True)
            run_ffmpeg(
                f'ffmpeg -y -i "{raw}" '
                f'-vf "scale=1080:1920:force_original_aspect_ratio=increase,'
                f'crop=1080:1920,setsar=1" '
                f'-t {trim_dur:.3f} -r 30 -c:v libx264 -preset fast -crf 22 -an '
                f'"{norm}" -loglevel error'
            )
            raw.unlink(missing_ok=True)
            d = get_duration(norm)
            norm_paths.append((str(norm), d))
            print(f"ok ({d:.1f}s)")
        except Exception as e:
            print(f"SKIP: {e}")
            raw.unlink(missing_ok=True)
    return norm_paths


# ─── CONCAT ─────────────────────────────────────────────────────────────────

def concat_clips(norm_paths, output_path):
    list_file = WORK_DIR / 'concat.txt'
    with open(list_file, 'w') as f:
        for path, _ in norm_paths:
            f.write(f"file '{path}'\n")
    run_ffmpeg(f'ffmpeg -y -f concat -safe 0 -i "{list_file}" -c copy "{output_path}" -loglevel error')
    return get_duration(output_path)


# ─── CAPTION HELPERS ─────────────────────────────────────────────────────────

def build_drawtext(captions, norm_paths, final_dur, font_size=50, y_pos='h-170', font_path=FONT_PATH):
    cum_starts = []
    t = 0.0
    for _, d in norm_paths:
        cum_starts.append(t)
        t += d

    parts = []
    for i, (start, (_, dur)) in enumerate(zip(cum_starts, norm_paths)):
        if i >= len(captions) or start >= final_dur:
            break
        ts = start + 1.5
        te = min(start + dur - 1.0, final_dur - 0.5)
        if te <= ts:
            te = start + dur
        cap = captions[i].replace("'", "")  # avoid shell quoting issues
        parts.append(
            f"drawtext=fontfile={font_path}:text='{cap}':"
            f"fontsize={font_size}:fontcolor=white@0.95:"
            f"x=(w-text_w)/2:y={y_pos}:"
            f"box=1:boxcolor=black@0.5:boxborderw=18:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.7:"
            f"enable='between(t,{ts:.2f},{te:.2f})'"
        )
    return ','.join(parts)


# ─── PRODUCE MAIN VIDEO (16:9, ~90s) ─────────────────────────────────────────

def produce_main(topic):
    print("\n=== MAIN VIDEO (landscape 16:9) ===")
    # Gather landscape clips
    px_clips = search_pixabay(topic['queries_landscape'])
    pe_clips = search_pexels_landscape(topic['queries_landscape'])
    all_clips = px_clips + pe_clips
    print(f"{len(all_clips)} landscape candidates")

    if len(all_clips) < 4:
        raise RuntimeError("Not enough landscape clips found")

    # Deduplicate by id
    seen = set()
    unique = []
    for c in all_clips:
        key = f"{c['source']}_{c['id']}"
        if key not in seen:
            seen.add(key)
            unique.append(c)

    norm_paths = normalize_landscape(unique, max_clips=12)
    if len(norm_paths) < 3:
        raise RuntimeError("Not enough clips normalized")

    combined = str(WORK_DIR / 'combined_main.mp4')
    combined_dur = concat_clips(norm_paths, combined)
    final_dur = min(combined_dur, 95)
    fo = final_dur - 3

    music_path = download_music(topic['music_url'])
    drawtext = build_drawtext(topic['captions_main'], norm_paths, final_dur,
                               font_size=50, y_pos='h-170')

    output = str(WORK_DIR / 'FINAL_main.mp4')
    print(f"Rendering {final_dur:.0f}s main video...")
    run_ffmpeg(
        f'ffmpeg -y '
        f'-i "{combined}" '
        f'-stream_loop -1 -i "{music_path}" '
        f'-filter_complex '
        f'"[1:a]volume=0.70,atrim=0:{final_dur:.2f},asetpts=PTS-STARTPTS[aout];'
        f'[0:v]fade=t=in:st=0:d=2,fade=t=out:st={fo:.2f}:d=3,{drawtext}[vout]" '
        f'-map "[vout]" -map "[aout]" '
        f'-t {final_dur:.2f} '
        f'-c:v libx264 -preset fast -crf 20 '
        f'-c:a aac -b:a 192k '
        f'"{output}" -loglevel error'
    )
    size_mb = Path(output).stat().st_size / 1e6
    print(f"Main video: {size_mb:.1f}MB | {get_duration(output):.1f}s")
    return output, norm_paths


# ─── PRODUCE SHORTS (9:16) ───────────────────────────────────────────────────

def produce_shorts(topic, landscape_norm_paths):
    print("\n=== SHORTS (portrait 9:16) ===")
    # Try portrait clips from Pexels
    portrait_clips = search_pexels_portrait(topic['queries_portrait'])
    print(f"{len(portrait_clips)} portrait candidates from Pexels")

    # Also crop landscape clips as fallback
    portrait_norm = normalize_portrait(portrait_clips, max_clips=8)

    # If not enough portrait clips, make portrait from landscape clips
    if len(portrait_norm) < 4:
        print("Not enough portrait clips, converting landscape clips...")
        for i, (lpath, ldur) in enumerate(landscape_norm_paths[:6]):
            ppath = str(WORK_DIR / f'norm_p_conv_{i:02d}.mp4')
            if not Path(ppath).exists():
                run_ffmpeg(
                    f'ffmpeg -y -i "{lpath}" '
                    f'-vf "crop=ih*9/16:ih,scale=1080:1920,setsar=1" '
                    f'-c:v libx264 -preset fast -crf 22 -an '
                    f'"{ppath}" -loglevel error'
                )
            portrait_norm.append((ppath, get_duration(ppath)))

    music_path = download_music(topic['music_url'])

    # SHORT 1 (~55s, 5-6 clips)
    s1_clips = portrait_norm[:6]
    s1_combined = str(WORK_DIR / 'combined_s1.mp4')
    s1_dur_raw = concat_clips(s1_clips, s1_combined)
    s1_dur = min(s1_dur_raw, 57)
    s1_fo = s1_dur - 2
    s1_drawtext = build_drawtext(
        topic['captions_short1'], s1_clips, s1_dur,
        font_size=60, y_pos='h-200'
    )
    short1_out = str(WORK_DIR / 'SHORT1.mp4')
    print(f"Rendering Short 1 ({s1_dur:.0f}s)...")
    run_ffmpeg(
        f'ffmpeg -y '
        f'-i "{s1_combined}" '
        f'-stream_loop -1 -i "{music_path}" '
        f'-filter_complex '
        f'"[1:a]volume=0.70,atrim=0:{s1_dur:.2f},asetpts=PTS-STARTPTS[aout];'
        f'[0:v]fade=t=in:st=0:d=1,fade=t=out:st={s1_fo:.2f}:d=2,{s1_drawtext}[vout]" '
        f'-map "[vout]" -map "[aout]" '
        f'-t {s1_dur:.2f} '
        f'-c:v libx264 -preset fast -crf 20 '
        f'-c:a aac -b:a 192k '
        f'"{short1_out}" -loglevel error'
    )
    s1_mb = Path(short1_out).stat().st_size / 1e6
    print(f"Short 1: {s1_mb:.1f}MB | {get_duration(short1_out):.1f}s")

    # SHORT 2 (~30s, 3 clips)
    s2_clips = portrait_norm[3:6] if len(portrait_norm) >= 6 else portrait_norm[-3:]
    if not s2_clips:
        s2_clips = portrait_norm[:3]
    s2_combined = str(WORK_DIR / 'combined_s2.mp4')
    s2_dur_raw = concat_clips(s2_clips, s2_combined)
    s2_dur = min(s2_dur_raw, 30)
    s2_fo = s2_dur - 1.5
    s2_drawtext = build_drawtext(
        topic['captions_short2'], s2_clips, s2_dur,
        font_size=65, y_pos='h-220'
    )
    short2_out = str(WORK_DIR / 'SHORT2.mp4')
    print(f"Rendering Short 2 ({s2_dur:.0f}s)...")
    run_ffmpeg(
        f'ffmpeg -y '
        f'-i "{s2_combined}" '
        f'-stream_loop -1 -i "{music_path}" '
        f'-filter_complex '
        f'"[1:a]volume=0.70,atrim=0:{s2_dur:.2f},asetpts=PTS-STARTPTS[aout];'
        f'[0:v]fade=t=in:st=0:d=1,fade=t=out:st={s2_fo:.2f}:d=1.5,{s2_drawtext}[vout]" '
        f'-map "[vout]" -map "[aout]" '
        f'-t {s2_dur:.2f} '
        f'-c:v libx264 -preset fast -crf 20 '
        f'-c:a aac -b:a 192k '
        f'"{short2_out}" -loglevel error'
    )
    s2_mb = Path(short2_out).stat().st_size / 1e6
    print(f"Short 2: {s2_mb:.1f}MB | {get_duration(short2_out):.1f}s")

    return short1_out, short2_out


# ─── CLEANUP ─────────────────────────────────────────────────────────────────

def cleanup():
    patterns = [
        str(WORK_DIR / 'raw_*.mp4'),
        str(WORK_DIR / 'norm_*.mp4'),
        str(WORK_DIR / 'combined_*.mp4'),
        str(WORK_DIR / 'concat.txt'),
        str(WORK_DIR / 'music.mp3'),
    ]
    removed = 0
    for pat in patterns:
        for f in glob.glob(pat):
            try:
                os.remove(f)
                removed += 1
            except Exception:
                pass
    print(f"Cleanup: {removed} temp files removed")
