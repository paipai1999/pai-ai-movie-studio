import os
import sys
import shutil
import subprocess
import re
from brain.memory import MovieState
import brain.config as cfg

# Force UTF-8 output on Windows to prevent emoji/Unicode encode errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

_DETECTED_ENCODER = None

def _get_safe_ascii_id(val: str, prefix: str = "vid", max_len: int = 16) -> str:
    """Generates an ASCII-safe unique identifier for temp files and FFmpeg filters,
    preventing libass fopen failures on Windows when video names contain Unicode/Burmese."""
    import hashlib
    raw = str(val or "").strip()
    stem = os.path.splitext(os.path.basename(raw))[0] if ("/" in raw or "\\" in raw or "." in raw) else raw
    ascii_clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', stem).strip('_')
    h = hashlib.md5(raw.encode('utf-8', errors='replace')).hexdigest()[:8]
    if ascii_clean:
        return f"{ascii_clean[:max_len]}_{h}"
    return f"{prefix}_{h}"

def _ensure_linux_cuda_ld_path():
    """Ensure Linux dynamic linker finds NVIDIA CUDA & NVENC driver libraries."""
    if not sys.platform.startswith("linux"):
        return
    import glob
    import subprocess
    import shutil

    ld_candidates = [
        "/usr/lib/x86_64-linux-gnu",
        "/usr/local/cuda/lib64",
        "/usr/local/nvidia/lib",
        "/usr/local/nvidia/lib64",
        "/usr/local/cuda/targets/x86_64-linux/lib",
        "/usr/lib/wsl/lib",
        "/usr/lib64",
    ]
    cur_ld = os.environ.get("LD_LIBRARY_PATH", "")
    extra_ld = [p for p in ld_candidates if os.path.exists(p) and p not in cur_ld]
    if extra_ld:
        os.environ["LD_LIBRARY_PATH"] = ":".join(extra_ld) + ((":" + cur_ld) if cur_ld else "")

    # Auto-repair libnvidia-encode.so.1 symlink if missing but versioned library exists on Kaggle/Ubuntu
    try:
        target_link = "/usr/lib/x86_64-linux-gnu/libnvidia-encode.so.1"
        if not os.path.exists(target_link):
            matches = glob.glob("/usr/lib/x86_64-linux-gnu/libnvidia-encode.so*") + \
                      glob.glob("/usr/local/nvidia/lib64/libnvidia-encode.so*") + \
                      glob.glob("/usr/lib64/libnvidia-encode.so*")
            valid_libs = [m for m in matches if not m.endswith(".so.1") and os.path.isfile(m)]
            if valid_libs:
                target_lib = sorted(valid_libs)[-1]
                try:
                    os.symlink(target_lib, target_link)
                except Exception:
                    try:
                        shutil.copy2(target_lib, target_link)
                    except Exception:
                        pass
        subprocess.run(["ldconfig"], capture_output=True, timeout=5)
    except Exception:
        pass

def _auto_setup_nvenc_linux() -> str:
    """Optionally cache a BtbN NVENC build locally without modifying system binaries."""
    import subprocess
    import tarfile
    
    if not sys.platform.startswith("linux"):
        return None

    # Check if NVIDIA GPU is available
    has_nvidia = False
    try:
        chk = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        if chk.returncode == 0:
            has_nvidia = True
    except Exception:
        pass
    if not has_nvidia:
        try:
            import torch
            has_nvidia = torch.cuda.is_available()
        except Exception:
            pass

    if not has_nvidia:
        return None

    # Configure LD_LIBRARY_PATH for NVIDIA CUDA and NVENC driver libraries on Linux
    _ensure_linux_cuda_ld_path()

    target_dir = os.path.abspath(os.path.join("temp", "ffmpeg_nvenc"))
    target = os.path.join(target_dir, "ffmpeg")
    ffprobe_target = os.path.join(target_dir, "ffprobe")
    if os.path.exists(target) and os.path.getsize(target) > 10000000:
        try:
            chk = subprocess.run([target, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=15)
            if chk.returncode == 0:
                os.environ["IMAGEIO_FFMPEG_EXE"] = target
                global _DETECTED_ENCODER
                _DETECTED_ENCODER = None
                return target
        except Exception:
            pass

    print("[*] Hardware Detection: NVIDIA GPU detected! Auto-fetching static NVENC FFmpeg build...")
    urls = [
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-linux64-gpl.tar.xz",
    ]
    try:
        build_dir = os.path.join("temp", "ffmpeg_nvenc_build")
        os.makedirs(build_dir, exist_ok=True)
        downloaded = False
        archive_path = os.path.join(build_dir, "ffmpeg.tar.xz")
        for url in urls:
            try:
                res = subprocess.run(["curl", "-L", "-f", "-s", "-A", "Mozilla/5.0", url, "-o", archive_path], timeout=90)
                if res.returncode == 0 and os.path.exists(archive_path) and os.path.getsize(archive_path) > 10000000:
                    downloaded = True
                    break
            except Exception:
                continue

        if not downloaded:
            print("[WARN] Could not download static NVENC FFmpeg build from primary or fallback URLs.")
            return None

        os.makedirs(target_dir, exist_ok=True)
        extracted = set()
        with tarfile.open(archive_path, "r:xz") as archive:
            for member in archive.getmembers():
                name = os.path.basename(member.name)
                if name not in {"ffmpeg", "ffprobe"} or not member.isfile():
                    continue
                destination = target if name == "ffmpeg" else ffprobe_target
                source = archive.extractfile(member)
                if source is None:
                    continue
                with open(destination, "wb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(destination, 0o755)
                extracted.add(name)
        if "ffmpeg" not in extracted:
            raise RuntimeError("Downloaded archive did not contain ffmpeg")
        try:
            os.remove(archive_path)
        except OSError:
            pass
        os.environ["IMAGEIO_FFMPEG_EXE"] = target
        
        chk = subprocess.run([target, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=15)
        if chk.returncode == 0:
            print(f"🚀 [OK] NVIDIA NVENC GPU Encoder ready and active ({target})!")
            _DETECTED_ENCODER = None
            return target
    except Exception as e:
        print(f"[!] Auto NVENC FFmpeg install notice: {e}")
    return None

def _get_ffmpeg_bin() -> str:
    import shutil
    import subprocess
    # Ensure Linux driver libraries are visible to dynamic linker before any test
    _ensure_linux_cuda_ld_path()

    # Search all candidate ffmpeg paths
    search_paths = [
        "/usr/local/bin/ffmpeg",
        shutil.which("ffmpeg"),
        os.environ.get("IMAGEIO_FFMPEG_EXE"),
        "/usr/bin/ffmpeg",
    ]
    existing = [p for p in search_paths if p and os.path.exists(p)]
    
    # Priority 1: Pick any binary that actively supports NVIDIA NVENC
    for p in existing:
        try:
            res = subprocess.run([p, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=15)
            if res.returncode == 0:
                os.environ["IMAGEIO_FFMPEG_EXE"] = p
                return p
        except Exception:
            pass

    # Priority 1.5: If on Linux with NVIDIA GPU, auto-setup NVENC build if not found
    nvenc_p = _auto_setup_nvenc_linux()
    if nvenc_p:
        return nvenc_p

    # Priority 2: Pick any binary that supports Intel QSV
    for p in existing:
        try:
            res = subprocess.run([p, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", "h264_qsv", "-f", "null", "-"], capture_output=True, timeout=15)
            if res.returncode == 0:
                os.environ["IMAGEIO_FFMPEG_EXE"] = p
                return p
        except Exception:
            pass

    if existing:
        return existing[0]

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_bin = get_ffmpeg_exe()
        os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_bin
        return ffmpeg_bin
    except Exception:
        return "ffmpeg"

def detect_hardware_encoder() -> dict:
    """Detects available hardware video encoders (NVIDIA NVENC, Intel QSV, AMD AMF) or CPU libx264."""
    global _DETECTED_ENCODER
    if _DETECTED_ENCODER is not None and _DETECTED_ENCODER.get("type") == "gpu":
        return _DETECTED_ENCODER

    import subprocess
    ffmpeg_bin = _get_ffmpeg_bin()

    candidates = [
        {"codec": "h264_nvenc", "label": "NVIDIA GPU (NVENC)", "type": "gpu", "preset": "p4"},
        {"codec": "h264_qsv", "label": "Intel QuickSync (QSV)", "type": "gpu", "preset": "faster"},
        {"codec": "h264_amf", "label": "AMD Radeon (AMF)", "type": "gpu", "preset": "speed"},
        {"codec": "libx264", "label": "CPU Multi-Core (libx264)", "type": "cpu", "preset": "veryfast"},
    ]

    chosen = candidates[-1]
    for c in candidates[:-1]:
        cmd = [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", c["codec"], "-f", "null", "-"]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=15)
            if res.returncode == 0:
                chosen = c
                break
        except Exception:
            continue

    _DETECTED_ENCODER = chosen
    return chosen

def _get_audio_duration(file_path: str) -> float:
    """Fast sub-millisecond audio duration check using soundfile, wave, or ffprobe (bypasses MoviePy)."""
    if not file_path or not os.path.exists(file_path):
        return 0.0
    try:
        import soundfile as sf
        return float(sf.info(file_path).duration)
    except Exception:
        pass
    if file_path.lower().endswith('.wav'):
        try:
            import wave
            with wave.open(file_path, 'rb') as wf:
                return float(wf.getnframes()) / float(wf.getframerate())
        except Exception:
            pass
    try:
        ffmpeg_bin = _get_ffmpeg_bin()
        res = subprocess.run(
            [ffmpeg_bin, "-i", file_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace"
        )
        import re
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr or "")
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0

def _get_video_info(video_path: str) -> dict:
    """Fast video metadata extraction using OpenCV or FFprobe in 10ms without MoviePy."""
    info = {"duration": 0.0, "width": 1920, "height": 1080, "fps": 24.0}
    if not video_path or not os.path.exists(video_path):
        return info
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
            fc = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            dur = fc / fps if fps > 0 else 0.0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
            cap.release()
            info["duration"] = max(0.0, dur)
            info["width"] = w
            info["height"] = h
            info["fps"] = fps
            return info
    except Exception:
        pass
    try:
        ffmpeg_bin = _get_ffmpeg_bin()
        res = subprocess.run(
            [ffmpeg_bin, "-i", video_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace"
        )
        import re
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr or "")
        if m:
            info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        dim = re.search(r",\s*(\d{3,4})x(\d{3,4})", res.stderr or "")
        if dim:
            info["width"] = int(dim.group(1))
            info["height"] = int(dim.group(2))
    except Exception:
        pass
    return info

def _has_audio_stream(video_path: str) -> bool:
    """Checks if a video file contains an audio stream using FFmpeg."""
    if not video_path or not os.path.exists(video_path):
        return False
    try:
        ffmpeg_bin = _get_ffmpeg_bin()
        res = subprocess.run(
            [ffmpeg_bin, "-i", video_path],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace"
        )
        return "Audio:" in (res.stderr or "")
    except Exception:
        return False

def _assemble_voiceover_track(clips_with_timing: list, total_duration: float, output_path: str, target_sr: int = 44100) -> str:
    """Stitches discrete speech clips into a contiguous PCM WAV buffer at C-speed in ~2 seconds."""
    import math
    import numpy as np
    total_samples = max(int(math.ceil(total_duration * target_sr)), target_sr)
    vo_buffer = np.zeros(total_samples, dtype=np.float32)

    for fpath, place_time, dur in clips_with_timing:
        if not fpath or not os.path.exists(fpath):
            continue
        try:
            import soundfile as sf
            data, c_sr = sf.read(fpath)
        except Exception:
            continue

        if data.ndim > 1:
            data = np.mean(data, axis=1)

        if c_sr != target_sr and len(data) > 0:
            try:
                import scipy.signal
                num_target = int(round(len(data) * float(target_sr) / float(c_sr)))
                data = scipy.signal.resample(data, num_target).astype(np.float32)
            except Exception:
                pass

        start_idx = int(place_time * target_sr)
        end_idx = min(start_idx + len(data), total_samples)
        if start_idx < total_samples and end_idx > start_idx:
            # Overlap-add mixing: blend overlapping speech tails cleanly rather than clipping/overwriting
            vo_buffer[start_idx:end_idx] += data[:end_idx - start_idx]

    # Prevent 16-bit integer clipping distortion if overlapping signals exceed unity
    max_val = float(np.max(np.abs(vo_buffer))) if len(vo_buffer) > 0 else 0.0
    if max_val > 1.0:
        vo_buffer = vo_buffer / max_val

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    import soundfile as sf
    sf.write(output_path, vo_buffer, target_sr, subtype='PCM_16')
    return output_path

class VideoMergerAgent:
    def __init__(
        self,
        output_dir: str = "outputs",
        subtitle_blur_override: bool = None,
        subtitle_mode: str = "burn",
        resolution: str = "1080p",
    ):
        self.output_dir = output_dir
        self.subtitle_blur_override = subtitle_blur_override
        self.subtitle_mode = str(subtitle_mode or "burn").lower()
        self.resolution = str(resolution or "1080p").lower()

    def merge_video(self, state, movie_path: str):
        output_dir = os.path.join(self.output_dir, state.project_dir)
        os.makedirs(output_dir, exist_ok=True)
        final_output = os.path.join(output_dir, "final_recap.mp4")

        config_data = cfg.load_config()
        copyright_cfg   = config_data.get("copyright_protection", {})
        copyright_enabled = copyright_cfg.get("enabled", True)
        blur_cfg        = config_data.get("subtitle_blur", {})
        blur_enabled    = blur_cfg.get("enabled", True)
        if self.subtitle_blur_override:
            blur_enabled = True
        blur_strength   = int(blur_cfg.get("blur_strength", 18))            # boxblur radius
        color_cfg       = config_data.get("color_grading", {})
        color_enabled   = color_cfg.get("enabled", True)
        cg_brightness   = float(color_cfg.get("brightness", 0.03))
        cg_contrast     = float(color_cfg.get("contrast", 1.02))
        cg_saturation   = float(color_cfg.get("saturation", 1.08))

        print(f"[*] VideoMerger: Starting video merge process (Copyright-Safe Mode: {copyright_enabled})...")

        # ── 1. Fast Video Metadata Extraction (10ms, Zero RAM) ───────────────
        v_info = _get_video_info(movie_path)
        video_dur = v_info.get("duration", 0.0)
        video_w = v_info.get("width", 1920)
        video_h = v_info.get("height", 1080)
        video_fps = v_info.get("fps", 24.0)
        print(f"[*] VideoMerger: Loaded video stream metadata ({video_dur:.1f}s, size: {video_w}x{video_h}, fps: {video_fps:.1f}).")

        # ── 2. Discover Speech Clips & Fast Duration Extraction ───────────────
        audio_items = []
        script_blocks = getattr(state, "generated_script", []) or []
        voiceover_dir = os.path.join(output_dir, "voiceover")
        if os.path.exists(voiceover_dir):
            try:
                script_blocks.sort(key=lambda x: float(x.get("start_sec") or 0.0) if isinstance(x, dict) else 0.0)
            except Exception as e:
                print(f"[WARN] Failed to sort script blocks: {e}")

            for sorted_idx, b in enumerate(script_blocks):
                if not isinstance(b, dict):
                    continue
                fname = f"scene_{(sorted_idx+1):04d}.mp3"
                fpath = os.path.join(voiceover_dir, fname)
                if not os.path.exists(fpath):
                    for root, _, files in os.walk(voiceover_dir):
                        if fname in files:
                            fpath = os.path.join(root, fname)
                            break
                if os.path.exists(fpath):
                    dur = _get_audio_duration(fpath)
                    if dur > 0:
                        audio_items.append((sorted_idx, fpath, dur, b))
                    else:
                        print(f"[WARN] VideoMerger: Audio file {fname} is empty or unreadable.")
                else:
                    print(f"[WARN] VideoMerger: Missing audio file {fname} for script block.")

        # ── 3. Absolute Scene-Anchor Sync Engine ──────────────────────────────
        subtitle_timings = []
        clips_with_timing = []
        n_blocks = len(audio_items)
        curr_t = 0.0
        if n_blocks > 0:
            print(f"[*] VideoMerger: Laying out {n_blocks} audio blocks across synced {video_dur:.1f}s video...")
            has_exact_timestamps = (
                len(script_blocks) > 0
                and isinstance(script_blocks[0], dict)
                and "start_sec" in script_blocks[0]
            )
            starts = []
            if has_exact_timestamps:
                print("[*] VideoMerger: Using EXACT Gemini timestamps for perfect audio sync.")
                for _, _, _, b in audio_items:
                    s = float(b.get("start_sec", 0.0))
                    if video_dur > 0 and s > video_dur - 1.0:
                        s = max(0.0, video_dur - 2.0)
                    starts.append(s)
            else:
                print("[WARN] No exact timestamps. Falling back to proportional dubbing mode.")
                starts = [0.2 + (idx / max(n_blocks - 1, 1)) * max(1.0, video_dur - 0.4) for idx in range(n_blocks)]

            for idx, (s_idx, fpath, dur, b) in enumerate(audio_items):
                orig_start = starts[idx]
                # True Scene-Anchor Sync:
                # If the previous clip overran slightly (<= 0.5s), anchor directly to orig_start.
                # Overlap-add audio mixing cleanly blends speech tails with zero cumulative drift.
                # If overrun is larger, place at curr_t, but whenever a scene gap occurs,
                # timing instantly snaps back to orig_start (0.000s drift).
                if orig_start >= curr_t - 0.5:
                    place_time = orig_start
                else:
                    place_time = curr_t

                if video_dur > 0 and place_time >= video_dur:
                    print(f"[*] VideoMerger: Audio clip {idx+1} falls past video duration ({video_dur:.1f}s), trimming remaining clips.")
                    break

                clips_with_timing.append((fpath, place_time, dur))
                curr_t = place_time + dur

                narration_text = b.get("narration", "").strip() if isinstance(b, dict) else ""
                subtitle_timings.append((place_time, dur, narration_text))

        state.subtitle_timings = subtitle_timings

        # ── 3b. Smart Outro & Subscribe Protection ───────────────────────────
        outro_cfg = config_data.get("outro_protection", {})
        auto_trim_enabled = bool(outro_cfg.get("auto_trim", True)) and not getattr(state, "no_smart_trim", False)
        manual_trim_sec = float(getattr(state, "trim_end", None) or outro_cfg.get("trim_end_seconds", 0.0) or 0.0)
        anti_sub_zoom_enabled = bool(outro_cfg.get("anti_subscribe_zoom", True))
        has_outro_card = bool(getattr(state, "outro_card", False) or outro_cfg.get("outro_card", False))

        effective_video_dur = video_dur
        if manual_trim_sec > 0.0 and video_dur > manual_trim_sec + 5.0:
            effective_video_dur = max(5.0, video_dur - manual_trim_sec)
            print(f"[OK] VideoMerger: Manual Outro Trim applied (-{manual_trim_sec:.1f}s) -> Render length: {effective_video_dur:.1f}s")
        elif auto_trim_enabled and clips_with_timing and video_dur > 15.0:
            last_narration_end = max([place_time + dur for _, place_time, dur in clips_with_timing])
            trailing_gap = video_dur - last_narration_end
            if trailing_gap > 3.0:
                # Add 2.0s graceful buffer after final spoken word, discarding trailing channel outro/subscribe cards
                effective_video_dur = min(video_dur, last_narration_end + 2.0)
                print(f"[OK] VideoMerger (Smart Outro Cut): Trimmed trailing outro from {video_dur:.1f}s -> {effective_video_dur:.1f}s (Cleaned {trailing_gap:.1f}s of source outro).")

        # ── 4. Linear PCM Voiceover Track Assembly in C-speed (~2s) ───────────
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)
        safe_id = _get_safe_ascii_id(movie_path)
        persistent_clean_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(final_output))[0]}_clean.mp4")
        clean_video_path = os.path.join(temp_dir, f"{safe_id}_clean.mp4")

        assembled_vo_path = os.path.join(temp_dir, f"{safe_id}_vo_track.wav")
        has_voiceover = False
        if clips_with_timing:
            print(f"[*] VideoMerger: Fast-assembling linear voiceover PCM track ({len(clips_with_timing)} clips) across {effective_video_dur:.1f}s in C-memory...")
            try:
                target_len = max(effective_video_dur, curr_t)
                _assemble_voiceover_track(clips_with_timing, target_len, assembled_vo_path)
                if os.path.exists(assembled_vo_path) and os.path.getsize(assembled_vo_path) > 1000:
                    has_voiceover = True
                    print("[OK] VideoMerger: Voiceover linear PCM track assembled in ~2 seconds.")
            except Exception as vo_err:
                print(f"[WARN] VideoMerger: Voiceover assembly notice: {vo_err}")

        # ── 5. Background Audio Source Determination ──────────────────────────
        has_no_vocals = False
        base_candidates = [
            getattr(state, "movie_name", None),
            os.path.splitext(os.path.basename(movie_path))[0],
        ]
        no_vocals_path = None
        for b_name in base_candidates:
            if not b_name:
                continue
            cand_path = os.path.join("temp", state.project_dir, "audio", "htdemucs", b_name, "no_vocals.wav")
            if os.path.exists(cand_path):
                no_vocals_path = cand_path
                has_no_vocals = True
                break

        bg_source_type = "none"
        bg_audio_file = None

        if has_no_vocals and not getattr(state, "skip_demucs", False):
            bg_source_type = "demucs"
            bg_audio_file = os.path.abspath(no_vocals_path)
            print("[*] VideoMerger: Found Demucs no_vocals.wav (SFX Only). Using as background audio.")
        elif getattr(state, "skip_demucs", False) or not has_no_vocals:
            print("[*] VideoMerger: Vocal separation bypassed / skip-demucs -> Muting original audio (zero English voice bleed).")
            bgm_cfg = config_data.get("bgm", {})
            bgm_folder = bgm_cfg.get("folder", "assets/bgm")
            bgm_track = None
            if os.path.exists(bgm_folder):
                candidates = [f for f in os.listdir(bgm_folder) if f.endswith(('.wav', '.mp3'))]
                for preferred in ["scifi_tension.wav", "dark_suspense.wav", "action_pulse.wav"]:
                    if preferred in candidates:
                        bgm_track = os.path.join(bgm_folder, preferred)
                        break
                if not bgm_track and candidates:
                    bgm_track = os.path.join(bgm_folder, candidates[0])

            if bgm_track and os.path.exists(bgm_track):
                bg_source_type = "bgm"
                bg_audio_file = os.path.abspath(bgm_track)
                print(f"[*] VideoMerger: Adding cinematic BGM -> {os.path.basename(bgm_track)}")
            else:
                bg_source_type = "none"
        else:
            if _has_audio_stream(movie_path):
                bg_source_type = "orig"
            else:
                bg_source_type = "none"

        # ── 6. Subtitles Preparation ──────────────────────────────────────────
        sub_cfg = config_data.get("subtitle_overlay", {})
        burn_subs = True
        if self.subtitle_mode in ["none", "off", "no"]:
            burn_subs = False
        elif self.subtitle_mode in ["burn", "hardsub", "both", "auto"]:
            burn_subs = True

        target_ass_path = None
        if subtitle_timings:
            self._export_standalone_srt(subtitle_timings, output_dir)
            if burn_subs:
                target_ass_path = os.path.join(temp_dir, f"myanmar_subs_{safe_id}.ass")
                sub_preset = getattr(state, "subtitle_style_preset", None) or sub_cfg.get("style_preset", "box_black")
                font_name = (sub_cfg.get("font_name") or "Myanmar Text") if sys.platform == "win32" else "Padauk"
                print(f"[*] VideoMerger: Preparing Myanmar ASS Subtitles (Style Preset: {sub_preset})...")
                self._write_ass(
                    timings       = subtitle_timings,
                    ass_path      = target_ass_path,
                    font_name     = font_name,
                    font_size     = int(sub_cfg.get("font_size", 40)),
                    bold          = bool(sub_cfg.get("bold", True)),
                    border_style  = int(sub_cfg.get("border_style", 3)),
                    outline_width = int(sub_cfg.get("outline_width", 3)),
                    margin_bottom = int(sub_cfg.get("margin_bottom", 50)),
                    max_chars     = int(sub_cfg.get("max_chars_per_line", 28)),
                    preset        = sub_preset,
                )
            else:
                print("[*] VideoMerger: Subtitle Mode is 'Voiceover Only' (Hardsub disabled). Exported standalone .srt subtitles.")

        # ── 7. Watermark / Brand Overlay ──────────────────────────────────────
        wm_cfg = config_data.get("watermark", {})
        wm_override = getattr(state, "watermark_override", {}) or {}
        wm_enabled = wm_override.get("enabled", wm_cfg.get("enabled", False))
        wm_png = None
        wm_pos = "bottom_left"
        wm_margin = 25
        # Apply the requested watermark to every rendered format, including
        # 9:16-only exports. Previously reels-only jobs silently skipped it.
        if wm_enabled:
            wm_text = wm_override.get("text") or wm_cfg.get("text", "Pai Ai Movie Studio")
            wm_opacity = float(wm_override.get("opacity") if wm_override.get("opacity") is not None else wm_cfg.get("opacity", 0.85))
            wm_font_size = int(wm_override.get("font_size") or wm_cfg.get("font_size", 28))
            wm_margin = int(wm_override.get("margin") or wm_cfg.get("margin", 25))
            wm_pos = str(wm_override.get("position") or wm_cfg.get("position", "bottom_left")).lower()
            wm_style = str(wm_override.get("style") or wm_cfg.get("style", "badge")).lower()
            wm_logo_path = wm_override.get("logo_path") or wm_cfg.get("logo_path", "")
            try:
                wm_png = self._create_watermark_image(
                    text=wm_text,
                    font_size=wm_font_size,
                    opacity=wm_opacity,
                    style=wm_style,
                    logo_path=wm_logo_path
                )
                if not (wm_png and os.path.exists(wm_png)):
                    wm_png = None
            except Exception as e:
                print(f"[WARN] VideoMerger: Failed to apply watermark: {e}")
                wm_png = None

        # ── 8. Thumbnail Intro & Vision Subtitle Blur ─────────────────────────
        thumb_intro_cfg = config_data.get("thumbnail_intro", {})
        thumb_intro_enabled = getattr(state, "thumbnail_intro_enabled", None)
        if thumb_intro_enabled is None:
            thumb_intro_enabled = thumb_intro_cfg.get("enabled", False)
        thumb_duration = float(thumb_intro_cfg.get("duration_sec", 3.0))
        thumbnail_path = os.path.join(output_dir, "thumbnail.jpg")
        has_thumb_intro = thumb_intro_enabled and os.path.exists(thumbnail_path)

        user_sub_mode = getattr(state, "subtitle_mode", "auto") if state is not None else "auto"
        user_sub_mode = user_sub_mode or "auto"
        do_blur = blur_enabled and (blur_strength > 0) and (user_sub_mode != "no")
        start_y_pct, height_pct = 0.82, 0.18
        subtitle_found = False
        if do_blur:
            if user_sub_mode == "yes":
                y, h, found = self._detect_subtitle_region_with_vision(movie_path, state=state)
                start_y_pct = y if found else 0.82
                height_pct = h if found else 0.18
                subtitle_found = True
            else:
                cache = getattr(state, "subtitle_detection", None) if state is not None else None
                if cache and cache.get("video_path") == os.path.abspath(movie_path):
                    start_y_pct = float(cache.get("start_y_pct", start_y_pct))
                    height_pct = float(cache.get("height_pct", height_pct))
                    subtitle_found = bool(cache.get("has_subtitles", False))
                else:
                    start_y_pct, height_pct, subtitle_found = self._detect_subtitle_region_with_vision(movie_path, state=state)
                if state is not None:
                    state.subtitle_detection = {
                        "video_path": os.path.abspath(movie_path),
                        "has_subtitles": subtitle_found,
                        "start_y_pct": start_y_pct,
                        "height_pct": height_pct,
                    }
            if not subtitle_found:
                do_blur = False

        # ── 9. Pure FFmpeg Single-Pass Video & Audio Compositing ──────────────
        single_pass_success = False
        ffmpeg_bin = _get_ffmpeg_bin()

        if ffmpeg_bin:
            enc_info = detect_hardware_encoder()
            codec = enc_info.get("codec", "libx264")
            preset = enc_info.get("preset", "faster")
            quality_args = ["-b:v", "6M", "-maxrate", "9M", "-bufsize", "12M"] if enc_info.get("type") == "gpu" else ["-crf", "20"]
            print(f"[*] VideoMerger (Single-Pass Engine): Assembling unified Filtergraph using {enc_info.get('label', codec)} [{codec}]...")

            sp_inputs = ["-i", os.path.abspath(movie_path)]
            next_idx = 1

            vo_input_idx = None
            if has_voiceover:
                sp_inputs.extend(["-i", os.path.abspath(assembled_vo_path)])
                vo_input_idx = next_idx
                next_idx += 1

            bg_input_idx = None
            if bg_source_type in ["demucs", "bgm"] and bg_audio_file and os.path.exists(bg_audio_file):
                sp_inputs.extend(["-i", os.path.abspath(bg_audio_file)])
                bg_input_idx = next_idx
                next_idx += 1

            wm_input_idx = None
            if wm_png and os.path.exists(wm_png):
                sp_inputs.extend(["-i", os.path.abspath(wm_png)])
                wm_input_idx = next_idx
                next_idx += 1

            has_ass = bool(burn_subs and target_ass_path and os.path.exists(target_ass_path))
            ass_dir = os.path.dirname(os.path.abspath(target_ass_path)) if (has_ass and target_ass_path) else (os.path.abspath(temp_dir) if os.path.exists(temp_dir) else os.path.abspath(output_dir))

            # --- FILTERGRAPH GENERATOR (Modular for safe fallbacks) ---
            def _build_filtergraph(include_blur: bool):
                # 30 FPS Cap: Cinema standard is 24-30 FPS. Capping 60 FPS down to 30 FPS cuts frames & encode time by 50%
                fps_cap = "fps=30," if float(video_fps) > 32.0 else ""
                scale_flt = "scale=-2:720," if self.resolution == "720p" else ""
                flt_parts = [
                    f"[0:v]{fps_cap}{scale_flt}crop=w='trunc(iw/2)*2':h='trunc(ih/2)*2'[v_base]"
                ]
                last_v = "[v_base]"

                if copyright_enabled:
                    mirror_enabled = copyright_cfg.get("mirror_video", False)
                    if mirror_enabled:
                        flt_parts.append(f"{last_v}hflip[v_flipped]")
                        last_v = "[v_flipped]"
                    resize_factor = float(copyright_cfg.get("resize_factor", 1.02))
                    if resize_factor != 1.0:
                        flt_parts.append(f"{last_v}scale=iw*{resize_factor}:ih*{resize_factor},crop=iw/{resize_factor}:ih/{resize_factor}[v_resized]")
                        last_v = "[v_resized]"

                if include_blur and subtitle_found:
                    r = blur_strength
                    blur_seg = (
                        f"{last_v}split=2[v_orig][v_sub_crop];"
                        f"[v_sub_crop]crop=iw:'trunc(ih*{height_pct:.3f}/2)*2':0:'trunc(ih*{start_y_pct:.3f}/2)*2',"
                        f"boxblur=luma_radius={r}:luma_power=2:chroma_radius={max(1,r//2)}:chroma_power=2[v_blurred_sub];"
                        f"[v_orig][v_blurred_sub]overlay=0:'trunc(H*{start_y_pct:.3f}/2)*2'[v_blended]"
                    )
                    flt_parts.append(blur_seg)
                    last_v = "[v_blended]"

                if color_enabled:
                    cg_str = (
                        f"{last_v}eq=brightness={cg_brightness:.3f}:contrast={cg_contrast:.3f}:saturation={cg_saturation:.3f},"
                        f"noise=alls=2:allf=t,vignette=PI/4[v_graded]"
                    )
                    flt_parts.append(cg_str)
                    last_v = "[v_graded]"

                # Anti-Subscribe Edge Zoom: subtly zoom in 9% during the closing 12 seconds to push YouTube end-screen cards offscreen
                if anti_sub_zoom_enabled and effective_video_dur > 25.0:
                    zoom_start_t = max(0.0, effective_video_dur - 12.0)
                    flt_parts.append(
                        f"{last_v}crop=w='if(gte(t,{zoom_start_t:.2f}), trunc(iw*0.91/2)*2, trunc(iw/2)*2)':"
                        f"h='if(gte(t,{zoom_start_t:.2f}), trunc(ih*0.91/2)*2, trunc(ih/2)*2)':"
                        f"x='(iw-ow)/2':y='(ih-oh)/2',scale=iw:ih[v_zoomed]"
                    )
                    last_v = "[v_zoomed]"

                # Split clean stream BEFORE applying 16:9 watermark and subtitles so persistent_clean_path
                # is truly clean (no duplicate watermark when exported to 9:16 Reels Canvas)
                flt_parts.append(f"{last_v}split=2[v_for_wm][v_for_clean]")

                if wm_input_idx is not None:
                    if wm_pos == "bottom_left":
                        pos_str = f"{wm_margin}:main_h-overlay_h-{wm_margin}"
                    elif wm_pos == "bottom_right":
                        pos_str = f"main_w-overlay_w-{wm_margin}:main_h-overlay_h-{wm_margin}"
                    elif wm_pos == "top_left":
                        pos_str = f"{wm_margin}:{wm_margin}"
                    elif wm_pos == "top_center":
                        pos_str = f"(main_w-overlay_w)/2:{wm_margin}"
                    else:
                        pos_str = f"main_w-overlay_w-{wm_margin}:{wm_margin}"
                    flt_parts.append(f"[v_for_wm][{wm_input_idx}:v]overlay={pos_str}[v_wm_done]")
                    v_sub_in = "[v_wm_done]"
                else:
                    v_sub_in = "[v_for_wm]"

                if has_ass:
                    ass_basename = os.path.basename(target_ass_path)
                    flt_parts.append(f"{v_sub_in}ass={ass_basename}[v_subbed]")
                    r_stream = "[v_subbed]"
                else:
                    r_stream = v_sub_in

                # Dynamic Audio Ducking & Compositing
                duck_cfg = config_data.get("audio_ducking", {})
                duck_enabled = duck_cfg.get("enabled", True)
                ambient_vol = float(duck_cfg.get("ambient_volume", 0.35))
                target_dur_str = f"{effective_video_dur:.2f}" if effective_video_dur > 0 else "600.00"

                if vo_input_idx is not None and (bg_input_idx is not None or bg_source_type == "orig"):
                    if bg_source_type == "bgm":
                        flt_parts.append(f"[{bg_input_idx}:a]aloop=loop=-1:size=2e+09,atrim=0:{target_dur_str},volume={ambient_vol:.2f}[bg_raw]")
                    elif bg_source_type == "demucs":
                        flt_parts.append(f"[{bg_input_idx}:a]apad=whole_dur={target_dur_str},atrim=0:{target_dur_str},volume={ambient_vol:.2f}[bg_raw]")
                    else:
                        flt_parts.append(f"[0:a]apad=whole_dur={target_dur_str},atrim=0:{target_dur_str},volume={ambient_vol:.2f}[bg_raw]")

                    if duck_enabled:
                        flt_parts.append(
                            f"[bg_raw][{vo_input_idx}:a]sidechaincompress=threshold=0.08:ratio=8:attack=100:release=400[ducked_bg]"
                        )
                        flt_parts.append(
                            f"[ducked_bg][{vo_input_idx}:a]amix=inputs=2:duration=first:dropout_transition=0,asplit=2[a_master1][a_master2]"
                        )
                    else:
                        flt_parts.append(
                            f"[bg_raw][{vo_input_idx}:a]amix=inputs=2:duration=first:dropout_transition=0,asplit=2[a_master1][a_master2]"
                        )
                elif vo_input_idx is not None:
                    flt_parts.append(f"[{vo_input_idx}:a]asplit=2[a_master1][a_master2]")
                elif bg_input_idx is not None or bg_source_type == "orig":
                    if bg_source_type == "bgm":
                        flt_parts.append(f"[{bg_input_idx}:a]aloop=loop=-1:size=2e+09,atrim=0:{target_dur_str},volume={ambient_vol:.2f},asplit=2[a_master1][a_master2]")
                    elif bg_source_type == "demucs":
                        flt_parts.append(f"[{bg_input_idx}:a]apad=whole_dur={target_dur_str},atrim=0:{target_dur_str},volume={ambient_vol:.2f},asplit=2[a_master1][a_master2]")
                    else:
                        flt_parts.append(f"[0:a]apad=whole_dur={target_dur_str},atrim=0:{target_dur_str},volume={ambient_vol:.2f},asplit=2[a_master1][a_master2]")
                else:
                    flt_parts.append(f"aevalsrc=0:d={target_dur_str},asplit=2[a_master1][a_master2]")

                return ";".join(flt_parts), r_stream

            dur_sec = effective_video_dur if effective_video_dur > 0 else (getattr(state, "duration_sec", 0.0) if state else 0.0)
            dyn_timeout = max(2400, int((dur_sec or 600.0) * 4.0))

            def _build_sp_cmd(curr_codec, curr_preset, curr_quality, curr_blur):
                flt_str, r_stream = _build_filtergraph(curr_blur)
                return [
                    ffmpeg_bin, "-y",
                    *sp_inputs,
                    "-filter_complex", flt_str,
                    "-map", r_stream, "-map", "[a_master1]",
                    "-t", f"{effective_video_dur:.2f}",
                    "-c:v", curr_codec, "-preset", curr_preset, *curr_quality,
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-c:a", "aac", "-b:a", "192k",
                    os.path.abspath(final_output),
                    "-map", "[v_for_clean]", "-map", "[a_master2]",
                    "-t", f"{effective_video_dur:.2f}",
                    "-c:v", curr_codec, "-preset", curr_preset, *curr_quality,
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-c:a", "aac", "-b:a", "192k",
                    os.path.abspath(persistent_clean_path),
                ]

            # Attempt single-pass: first with blur (if enabled), fallback without blur if filter fails
            blur_attempts = [True, False] if (do_blur and subtitle_found) else [False]

            for attempt_idx, curr_blur in enumerate(blur_attempts):
                if single_pass_success:
                    break
                
                sp_cmd = _build_sp_cmd(codec, preset, quality_args, curr_blur)

                print(f"[*] VideoMerger (Single-Pass Engine): Rendering both Recap & Clean Canvas (Blur={curr_blur}, Encoder={codec})...")
                try:
                    res = subprocess.run(
                        sp_cmd, cwd=ass_dir, capture_output=True, text=True,
                        timeout=dyn_timeout, encoding="utf-8", errors="replace"
                    )
                    if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                        print("\n🛑 [STOP] VideoMerger: FFmpeg single-pass cancelled by user.")
                        raise InterruptedError("Video rendering was cancelled by user.")
                    if res.returncode == 0 and os.path.exists(final_output) and os.path.getsize(final_output) > 1000:
                        single_pass_success = True
                        try:
                            shutil.copy2(persistent_clean_path, clean_video_path)
                        except Exception:
                            pass
                        state.clean_video_path = persistent_clean_path
                        print(f"🚀 [OK] VideoMerger: Pure FFmpeg Single-Pass Video & Audio Compositing COMPLETE! ({codec})")
                        break
                    else:
                        err_snippet = res.stderr[-500:] if res.stderr else "Unknown error"
                        print(f"[WARN] VideoMerger: Single-pass hardware render failed ({err_snippet}). Retrying with CPU libx264...")
                        fb_cmd = _build_sp_cmd("libx264", "superfast", ["-crf", "20"], curr_blur)
                        res_cpu = subprocess.run(
                            fb_cmd, cwd=ass_dir, capture_output=True, text=True,
                            timeout=dyn_timeout, encoding="utf-8", errors="replace"
                        )
                        if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                            print("\n🛑 [STOP] VideoMerger: FFmpeg CPU single-pass cancelled by user.")
                            raise InterruptedError("Video rendering was cancelled by user.")
                        if res_cpu.returncode == 0 and os.path.exists(final_output) and os.path.getsize(final_output) > 1000:
                            single_pass_success = True
                            try:
                                shutil.copy2(persistent_clean_path, clean_video_path)
                            except Exception:
                                pass
                            state.clean_video_path = persistent_clean_path
                            print("🚀 [OK] VideoMerger: Pure FFmpeg Single-Pass CPU Video & Audio Compositing COMPLETE!")
                            break
                        elif curr_blur and attempt_idx == 0 and len(blur_attempts) > 1:
                            print("[WARN] VideoMerger: Blur filter failed. Retrying Pure FFmpeg without blur filter to prevent slow MoviePy fallback...")
                except InterruptedError:
                    raise
                except Exception as spe:
                    print(f"[WARN] Single-pass execution exception: {spe}")

            if has_thumb_intro:
                print(f"[*] VideoMerger: Prepending {thumb_duration:.1f}s thumbnail intro with Pure FFmpeg...")
                ok1 = self._prepend_thumbnail_intro_ffmpeg(thumbnail_path, final_output, thumb_duration=thumb_duration)
                ok2 = False
                if os.path.exists(persistent_clean_path):
                    ok2 = self._prepend_thumbnail_intro_ffmpeg(thumbnail_path, persistent_clean_path, thumb_duration=thumb_duration)
                    try:
                        shutil.copy2(persistent_clean_path, clean_video_path)
                    except Exception:
                        pass
                state.thumbnail_intro_applied = bool(ok1 or ok2)
            else:
                state.thumbnail_intro_applied = False

            if has_outro_card:
                print("[*] VideoMerger: Appending 3.0s 'Pai AI Movie Studio' branded Outro Card...")
                ok_out1 = self._append_outro_card_ffmpeg(final_output, outro_duration=3.0)
                ok_out2 = False
                if os.path.exists(persistent_clean_path):
                    ok_out2 = self._append_outro_card_ffmpeg(persistent_clean_path, outro_duration=3.0)
                    try:
                        shutil.copy2(persistent_clean_path, clean_video_path)
                    except Exception:
                        pass
                state.outro_card_applied = bool(ok_out1 or ok_out2)
            else:
                state.outro_card_applied = False

            return state

        # ── 10. Fallback Legacy Path (Only if Single-Pass failed) ──
        return self._legacy_moviepy_merge(
            state, movie_path, output_dir, final_output, persistent_clean_path, clean_video_path,
            config_data, burn_subs, target_ass_path, subtitle_timings
        )

    @staticmethod
    def _prepend_thumbnail_intro_ffmpeg(thumb_path: str, video_path: str, thumb_duration: float = 3.0) -> bool:
        """Prepends a 3-second thumbnail intro to the rendered video using fast FFmpeg concat."""
        ffmpeg_bin = _get_ffmpeg_bin()
        if not ffmpeg_bin or not os.path.exists(thumb_path) or not os.path.exists(video_path):
            return False

        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
            if fps <= 0 or fps > 120:
                fps = 24.0
            frame_cnt = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            vid_duration = (frame_cnt / fps) if fps > 0 and frame_cnt > 0 else 600.0
            cap.release()
        except Exception:
            w, h, fps, vid_duration = 1920, 1080, 24.0, 600.0

        tmp_dir = os.path.dirname(os.path.abspath(video_path))
        base_name, _ = os.path.splitext(os.path.basename(video_path))
        intro_ts = os.path.join(tmp_dir, f"{base_name}_intro_tmp.mp4")
        concat_out = os.path.join(tmp_dir, f"{base_name}_with_intro.mp4")

        try:
            intro_cmd = [
                ffmpeg_bin, "-y",
                "-loop", "1", "-framerate", str(fps), "-t", str(thumb_duration),
                "-i", os.path.abspath(thumb_path),
                "-f", "lavfi", "-t", str(thumb_duration), "-i", "anullsrc=r=44100:cl=stereo",
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                intro_ts
            ]
            res1 = subprocess.run(intro_cmd, capture_output=True, timeout=60)
            if res1.returncode != 0 or not os.path.exists(intro_ts):
                err = (res1.stderr.decode("utf-8", errors="replace") if isinstance(res1.stderr, bytes) else str(res1.stderr or ""))[-300:]
                print(f"[WARN] Failed to generate FFmpeg thumbnail intro: {err}")
                return False

            enc_info = detect_hardware_encoder()
            codec = enc_info.get("codec", "libx264")
            preset = enc_info.get("preset", "veryfast")
            quality_args = ["-b:v", "6M", "-maxrate", "9M", "-bufsize", "12M"] if enc_info.get("type") == "gpu" else ["-crf", "20"]

            concat_cmd = [
                ffmpeg_bin, "-y",
                "-i", intro_ts,
                "-i", os.path.abspath(video_path),
                "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", codec, "-preset", preset, *quality_args,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                concat_out
            ]
            concat_timeout = max(1800, int(vid_duration * 3.0))
            res2 = subprocess.run(concat_cmd, capture_output=True, timeout=concat_timeout)
            if res2.returncode == 0 and os.path.exists(concat_out) and os.path.getsize(concat_out) > 1000:
                shutil.move(concat_out, video_path)
                print(f"🎉 [OK] VideoMerger: Prepended {thumb_duration:.1f}s thumbnail intro with Pure FFmpeg!")
                return True
            else:
                err2 = (res2.stderr.decode("utf-8", errors="replace") if isinstance(res2.stderr, bytes) else str(res2.stderr or ""))[-400:]
                print(f"[WARN] VideoMerger: FFmpeg thumbnail intro concat failed (code={res2.returncode}): {err2}")
        except Exception as te:
            print(f"[WARN] VideoMerger: FFmpeg thumbnail intro prepend failed: {te}")
        finally:
            for p in [intro_ts, concat_out]:
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
        return False

    @staticmethod
    def _append_outro_card_ffmpeg(video_path: str, outro_duration: float = 3.0) -> bool:
        """Appends a 3-second 'Pai AI Movie Studio' branded Outro Card to the rendered video."""
        ffmpeg_bin = _get_ffmpeg_bin()
        if not ffmpeg_bin or not os.path.exists(video_path):
            return False

        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
            if fps <= 0 or fps > 120:
                fps = 24.0
            frame_cnt = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            vid_duration = (frame_cnt / fps) if fps > 0 and frame_cnt > 0 else 600.0
            cap.release()
        except Exception:
            w, h, fps, vid_duration = 1920, 1080, 24.0, 600.0

        tmp_dir = os.path.dirname(os.path.abspath(video_path))
        base_name, _ = os.path.splitext(os.path.basename(video_path))
        outro_img_path = os.path.join(tmp_dir, f"{base_name}_outro_card.png")
        outro_ts = os.path.join(tmp_dir, f"{base_name}_outro_tmp.mp4")
        concat_out = os.path.join(tmp_dir, f"{base_name}_with_outro.mp4")

        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new('RGB', (w, h), (15, 23, 42))
            draw = ImageDraw.Draw(img)

            # Responsive badge and text layout based on aspect ratio (16:9 vs 9:16)
            is_portrait = h > w
            if is_portrait:
                badge_w = int(w * 0.84)
                badge_h = int(badge_w * 0.22)
                bx = (w - badge_w) // 2
                by = (h - badge_h) // 2 - int(h * 0.06)
                radius = 28
                border_w = 4
                font_title_sz = max(18, int(w * 0.055))
                font_thanks_sz = max(16, int(w * 0.048))
                font_sub_sz = max(14, int(w * 0.038))
                sub_offset = int(h * 0.09)
            else:
                scale_factor = min(w / 1920.0, h / 1080.0)
                badge_w = int(720 * scale_factor)
                badge_h = int(140 * scale_factor)
                bx = (w - badge_w) // 2
                by = (h - badge_h) // 2 - int(60 * scale_factor)
                radius = int(24 * scale_factor)
                border_w = max(2, int(4 * scale_factor))
                font_title_sz = max(16, int(52 * scale_factor))
                font_thanks_sz = max(14, int(42 * scale_factor))
                font_sub_sz = max(12, int(32 * scale_factor))
                sub_offset = int(120 * scale_factor)

            draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h], radius=radius, fill=(30, 41, 59), outline=(234, 179, 8), width=border_w)

            font_path = os.path.join('assets', 'fonts', 'Padauk.ttf')
            try:
                font_title = ImageFont.truetype(font_path, font_title_sz)
                font_thanks = ImageFont.truetype(font_path, font_thanks_sz)
                font_sub = ImageFont.truetype(font_path, font_sub_sz)
            except Exception:
                font_title = font_thanks = font_sub = ImageFont.load_default()

            draw.text((w // 2, by + badge_h // 2), "Pai Ai Movie Studio", fill=(255, 255, 255), font=font_title, anchor="mm")
            draw.text((w // 2, by + badge_h + (int(h * 0.04) if is_portrait else int(60 * scale_factor))), "ကျေးဇူးတင်ပါတယ်", fill=(234, 179, 8), font=font_thanks, anchor="mm")
            subtext = "နောက်ထပ် ဇာတ်ကားကောင်းများစွာအတွက်\nLike & Follow လုပ်ထားပေးကြပါဦးခင်ဗျား" if is_portrait else "နောက်ထပ် ဇာတ်ကားကောင်းများစွာအတွက် Like & Follow လုပ်ထားပေးကြပါဦးခင်ဗျား"
            draw.multiline_text((w // 2, by + badge_h + sub_offset), subtext, fill=(203, 213, 225), font=font_sub, anchor="mm", align="center", spacing=12)

            img.save(outro_img_path, "PNG")

            # Create 3-second video clip with fade in & fade out
            outro_cmd = [
                ffmpeg_bin, "-y",
                "-loop", "1", "-framerate", str(fps), "-t", str(outro_duration),
                "-i", os.path.abspath(outro_img_path),
                "-f", "lavfi", "-t", str(outro_duration), "-i", "anullsrc=r=44100:cl=stereo",
                "-vf", f"scale={w}:{h},fade=t=in:st=0:d=0.5,fade=t=out:st={outro_duration-0.5:.2f}:d=0.5,format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                outro_ts
            ]
            res1 = subprocess.run(outro_cmd, capture_output=True, timeout=60)
            if res1.returncode != 0 or not os.path.exists(outro_ts):
                err = (res1.stderr.decode("utf-8", errors="replace") if isinstance(res1.stderr, bytes) else str(res1.stderr or ""))[-300:]
                print(f"[WARN] Failed to generate FFmpeg outro card: {err}")
                return False

            enc_info = detect_hardware_encoder()
            codec = enc_info.get("codec", "libx264")
            preset = enc_info.get("preset", "veryfast")
            quality_args = ["-b:v", "6M", "-maxrate", "9M", "-bufsize", "12M"] if enc_info.get("type") == "gpu" else ["-crf", "20"]

            concat_cmd = [
                ffmpeg_bin, "-y",
                "-i", os.path.abspath(video_path),
                "-i", outro_ts,
                "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", codec, "-preset", preset, *quality_args,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                concat_out
            ]
            concat_timeout = max(1800, int(vid_duration * 3.0))
            res2 = subprocess.run(concat_cmd, capture_output=True, timeout=concat_timeout)
            if res2.returncode == 0 and os.path.exists(concat_out) and os.path.getsize(concat_out) > 1000:
                shutil.move(concat_out, video_path)
                print(f"🎉 [OK] VideoMerger: Appended {outro_duration:.1f}s 'Pai AI Movie Studio' Outro Card!")
                return True
            else:
                err2 = (res2.stderr.decode("utf-8", errors="replace") if isinstance(res2.stderr, bytes) else str(res2.stderr or ""))[-400:]
                print(f"[WARN] VideoMerger: FFmpeg outro card concat failed (code={res2.returncode}): {err2}")
        except Exception as te:
            print(f"[WARN] VideoMerger: FFmpeg outro card append failed: {te}")
        finally:
            for p in [outro_img_path, outro_ts, concat_out]:
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
        return False

    def _legacy_moviepy_merge(
        self,
        state,
        movie_path: str,
        output_dir: str,
        final_output: str,
        persistent_clean_path: str,
        clean_video_path: str,
        config_data: dict,
        burn_subs: bool = True,
        target_ass_path: str = None,
        subtitle_timings: list = None,
    ):
        """Legacy MoviePy Multi-Pass merge safety net (used only if FFmpeg Single-Pass fails)."""
        print("[*] VideoMerger: Falling back to Legacy Multi-Pass Export...")
        try:
            from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
        except ImportError:
            try:
                from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip
            except ImportError:
                print("[ERROR] VideoMerger: moviepy is not installed for legacy fallback. Run: pip install moviepy")
                return state

        main_video = None
        sfx_only_audio = None
        intro_clip = None
        final_clip = None
        audio_clips = []
        positioned_clips = []

        try:
            copyright_cfg   = config_data.get("copyright_protection", {})
            copyright_enabled = copyright_cfg.get("enabled", True)
            blur_cfg        = config_data.get("subtitle_blur", {})
            blur_enabled    = blur_cfg.get("enabled", True)
            if self.subtitle_blur_override:
                blur_enabled = True
            blur_region_pct = float(blur_cfg.get("region_height_pct", 0.18))
            blur_strength   = int(blur_cfg.get("blur_strength", 18))
            color_cfg       = config_data.get("color_grading", {})
            color_enabled   = color_cfg.get("enabled", True)
            cg_brightness   = float(color_cfg.get("brightness", 0.03))
            cg_contrast     = float(color_cfg.get("contrast", 1.02))
            cg_saturation   = float(color_cfg.get("saturation", 1.08))

            voiceover_dir = os.path.join(output_dir, "voiceover")
            script_blocks = getattr(state, "generated_script", []) or []
            script_blocks_with_audio = []
            if os.path.exists(voiceover_dir):
                try:
                    script_blocks.sort(key=lambda x: float(x.get("start_sec") or 0.0) if isinstance(x, dict) else 0.0)
                except Exception as e:
                    print(f"[WARN] Failed to sort script blocks: {e}")

                for sorted_idx, b in enumerate(script_blocks):
                    if not isinstance(b, dict):
                        continue
                    fname = f"scene_{(sorted_idx+1):04d}.mp3"
                    fpath = os.path.join(voiceover_dir, fname)
                    if not os.path.exists(fpath):
                        for root, _, files in os.walk(voiceover_dir):
                            if fname in files:
                                fpath = os.path.join(root, fname)
                                break
                    if os.path.exists(fpath):
                        try:
                            audio_clips.append(AudioFileClip(fpath))
                            script_blocks_with_audio.append(b)
                        except Exception as e:
                            print(f"[WARN] VideoMerger: Failed to load voiceover {fname}: {e}")

            script_blocks = script_blocks_with_audio
            main_video = VideoFileClip(movie_path)

            has_no_vocals = False
            base_candidates = [
                getattr(state, "movie_name", None),
                os.path.splitext(os.path.basename(movie_path))[0],
            ]
            no_vocals_path = None
            for b_name in base_candidates:
                if not b_name:
                    continue
                cand_path = os.path.join("temp", state.project_dir, "audio", "htdemucs", b_name, "no_vocals.wav")
                if os.path.exists(cand_path):
                    no_vocals_path = cand_path
                    break

            if no_vocals_path and os.path.exists(no_vocals_path):
                has_no_vocals = True
                try:
                    sfx_only_audio = AudioFileClip(no_vocals_path)
                    if hasattr(main_video, "with_audio"):
                        main_video = main_video.with_audio(sfx_only_audio)
                    else:
                        main_video = main_video.set_audio(sfx_only_audio)
                except Exception as e:
                    print(f"[WARN] VideoMerger: Failed to load no_vocals.wav: {e}")

            w, h = main_video.size
            new_w = w if w % 2 == 0 else w - 1
            new_h = h if h % 2 == 0 else h - 1
            if (new_w, new_h) != (w, h):
                try:
                    try:
                        from moviepy.video.fx.Crop import Crop
                        main_video = main_video.with_effects([Crop(x1=0, y1=0, x2=new_w, y2=new_h)])
                    except ImportError:
                        import moviepy.video.fx.all as vfx
                        main_video = main_video.fx(vfx.crop, x1=0, y1=0, x2=new_w, y2=new_h)
                except Exception as e:
                    print(f"[WARN] Failed to crop odd dimensions: {e}")

            if copyright_enabled:
                effects = []
                mirror_enabled = copyright_cfg.get("mirror_video", False)
                if mirror_enabled:
                    try:
                        try:
                            from moviepy.video.fx.MirrorX import MirrorX
                            effects.append(MirrorX())
                        except Exception:
                            import moviepy.video.fx.all as vfx
                            main_video = main_video.fx(vfx.mirror_x)
                    except Exception as e:
                        print(f"[WARN] Failed to apply mirror effect: {e}")

                resize_factor = float(copyright_cfg.get("resize_factor", 1.02))
                if resize_factor != 1.0:
                    try:
                        try:
                            from moviepy.video.fx.Resize import Resize
                            effects.append(Resize(resize_factor))
                        except Exception:
                            import moviepy.video.fx.all as vfx
                            main_video = main_video.fx(vfx.resize, resize_factor)
                    except Exception as e:
                        print(f"[WARN] Failed to apply resize: {e}")

                try:
                    try:
                        from moviepy.video.fx.FadeIn import FadeIn
                        from moviepy.video.fx.FadeOut import FadeOut
                        effects.append(FadeIn(1.0))
                        effects.append(FadeOut(1.0))
                    except Exception:
                        import moviepy.video.fx.all as vfx
                        main_video = main_video.fx(vfx.fadein, 1.0).fx(vfx.fadeout, 1.0)
                except Exception as e:
                    print(f"[WARN] Failed to apply fade transitions: {e}")

                if effects and hasattr(main_video, "with_effects"):
                    try:
                        main_video = main_video.with_effects(effects)
                    except Exception:
                        pass

            if audio_clips:
                video_dur = main_video.duration
                n_blocks = len(audio_clips)
                has_exact_timestamps = (
                    len(script_blocks) > 0
                    and isinstance(script_blocks[0], dict)
                    and "start_sec" in script_blocks[0]
                )
                starts = []
                if has_exact_timestamps:
                    for b in script_blocks:
                        s = float(b.get("start_sec", 0.0))
                        if s > video_dur - 1.0:
                            s = max(0.0, video_dur - 2.0)
                        starts.append(s)
                else:
                    starts = [0.2 + (idx / max(n_blocks - 1, 1)) * (video_dur - 0.4) for idx in range(n_blocks)]

                curr_t = 0.0
                legacy_subtitle_timings = []
                for idx, c in enumerate(audio_clips):
                    orig_start = starts[idx]
                    if orig_start >= curr_t - 0.5:
                        place_time = orig_start
                    else:
                        place_time = curr_t
                    if place_time >= video_dur:
                        break
                    if hasattr(c, "with_start"):
                        positioned_clips.append(c.with_start(place_time))
                    else:
                        positioned_clips.append(c.set_start(place_time))
                    curr_t = place_time + c.duration
                    if idx < len(script_blocks):
                        b = script_blocks[idx]
                        narration_text = b.get("narration", "").strip() if isinstance(b, dict) else ""
                        legacy_subtitle_timings.append((place_time, c.duration, narration_text))

                if not subtitle_timings:
                    subtitle_timings = legacy_subtitle_timings
                state.subtitle_timings = subtitle_timings

                duck_cfg = config_data.get("audio_ducking", {})
                duck_enabled = duck_cfg.get("enabled", True)
                duck_vol = float(duck_cfg.get("duck_volume", 0.12))
                ambient_vol = float(duck_cfg.get("ambient_volume", 0.35))

                orig_audio = main_video.audio
                if orig_audio is not None and duck_enabled and positioned_clips:
                    try:
                        import numpy as np
                        raw_intervals = [
                            (max(0.0, float(getattr(c, "start", 0.0) or 0.0) - 0.25),
                             float(getattr(c, "start", 0.0) or 0.0) + float(getattr(c, "duration", 0.0) or 0.0) + 0.25)
                            for c in positioned_clips
                        ]
                        raw_intervals.sort(key=lambda x: x[0])
                        merged_intervals = []
                        for s, e in raw_intervals:
                            if not merged_intervals or merged_intervals[-1][1] < s:
                                merged_intervals.append([s, e])
                            else:
                                merged_intervals[-1][1] = max(merged_intervals[-1][1], e)

                        def duck_transform(get_frame, t):
                            frame = get_frame(t)
                            if np.isscalar(t):
                                is_speech = any(s <= t <= e for s, e in merged_intervals)
                                return (duck_vol if is_speech else ambient_vol) * frame
                            else:
                                t_min, t_max = t[0], t[-1]
                                vol = np.full(t.shape[0], ambient_vol, dtype=np.float32)
                                for s, e in merged_intervals:
                                    if e < t_min: continue
                                    if s > t_max: break
                                    vol[(t >= s) & (t <= e)] = duck_vol
                                if hasattr(frame, 'ndim') and frame.ndim == 2:
                                    return vol[:, np.newaxis] * frame
                                return vol * frame

                        orig_audio = orig_audio.transform(duck_transform)
                    except Exception:
                        pass

                bgm_clip = None
                if not has_no_vocals or getattr(state, "skip_demucs", False):
                    orig_audio = None
                    bgm_cfg = config_data.get("bgm", {})
                    bgm_folder = bgm_cfg.get("folder", "assets/bgm")
                    bgm_track = None
                    if os.path.exists(bgm_folder):
                        candidates = [f for f in os.listdir(bgm_folder) if f.endswith(('.wav', '.mp3'))]
                        for preferred in ["scifi_tension.wav", "dark_suspense.wav", "action_pulse.wav"]:
                            if preferred in candidates:
                                bgm_track = os.path.join(bgm_folder, preferred)
                                break
                        if not bgm_track and candidates:
                            bgm_track = os.path.join(bgm_folder, candidates[0])

                    if bgm_track and os.path.exists(bgm_track):
                        try:
                            raw_bgm = AudioFileClip(bgm_track)
                            try:
                                from moviepy.audio.fx.AudioLoop import AudioLoop
                                from moviepy.audio.fx.MultiplyVolume import MultiplyVolume
                                bgm_clip = raw_bgm.with_effects([AudioLoop(duration=main_video.duration), MultiplyVolume(0.18)])
                            except Exception:
                                import moviepy.audio.fx.all as afx
                                bgm_clip = afx.audio_loop(raw_bgm, duration=main_video.duration)
                                bgm_clip = afx.volumex(bgm_clip, 0.18)
                        except Exception:
                            pass

                audio_components = []
                if orig_audio is not None:
                    audio_components.append(orig_audio)
                if bgm_clip is not None:
                    audio_components.append(bgm_clip)
                audio_components.extend(positioned_clips)

                final_audio = CompositeAudioClip(audio_components)
                if hasattr(main_video, "with_audio"):
                    main_video = main_video.with_audio(final_audio)
                else:
                    main_video = main_video.set_audio(final_audio)

                final_clip = main_video
            else:
                final_clip = main_video

            thumb_intro_cfg = config_data.get("thumbnail_intro", {})
            thumb_intro_enabled = getattr(state, "thumbnail_intro_enabled", None)
            if thumb_intro_enabled is None:
                thumb_intro_enabled = thumb_intro_cfg.get("enabled", False)
            thumb_duration = float(thumb_intro_cfg.get("duration_sec", 3.0))
            thumbnail_path = os.path.join(output_dir, "thumbnail.jpg")
            has_thumb_intro = thumb_intro_enabled and os.path.exists(thumbnail_path)

            if has_thumb_intro:
                try:
                    try:
                        from moviepy import ImageClip, concatenate_videoclips
                    except ImportError:
                        from moviepy.editor import ImageClip, concatenate_videoclips
                    intro_clip = ImageClip(thumbnail_path)
                    if hasattr(intro_clip, "with_duration"):
                        intro_clip = intro_clip.with_duration(thumb_duration)
                    else:
                        intro_clip = intro_clip.set_duration(thumb_duration)
                    fps_val = final_clip.fps if final_clip.fps else 24
                    if hasattr(intro_clip, "with_fps"):
                        intro_clip = intro_clip.with_fps(fps_val)
                    else:
                        intro_clip.fps = fps_val
                    w, h = intro_clip.size
                    new_w, new_h = final_clip.size
                    if (w, h) != (new_w, new_h):
                        try:
                            from moviepy.video.fx.Resize import Resize
                            intro_clip = intro_clip.with_effects([Resize((new_w, new_h))])
                        except Exception:
                            pass
                    final_clip = concatenate_videoclips([intro_clip, final_clip], method="compose")
                    if subtitle_timings:
                        subtitle_timings = [(start + thumb_duration, dur, txt) for (start, dur, txt) in subtitle_timings]
                        state.subtitle_timings = subtitle_timings
                except Exception as e:
                    print(f"[WARN] VideoMerger: Failed to stitch thumbnail intro: {e}")

            enc_info = detect_hardware_encoder()
            print(f"[*] VideoMerger (Hardware Acceleration): Exporting legacy video using {enc_info['label']} [{enc_info['codec']}]...")
            try:
                final_clip.write_videofile(
                    final_output,
                    codec=enc_info["codec"],
                    audio_codec='aac',
                    bitrate='4500k',
                    preset=enc_info.get("preset", "faster"),
                    threads=4,
                    ffmpeg_params=["-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
                    logger='bar'
                )
            except Exception as enc_err:
                print(f"[WARN] Hardware encoder '{enc_info['codec']}' failed: {enc_err}. Falling back to CPU libx264...")
                final_clip.write_videofile(
                    final_output,
                    codec='libx264',
                    audio_codec='aac',
                    bitrate='4500k',
                    preset='superfast',
                    threads=4,
                    ffmpeg_params=["-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
                    logger='bar'
                )

            try:
                shutil.copy2(final_output, clean_video_path)
                shutil.copy2(final_output, persistent_clean_path)
                state.clean_video_path = persistent_clean_path
            except Exception as ce:
                print(f"[WARN] VideoMerger: Could not cache clean video copy: {ce}")
                state.clean_video_path = clean_video_path

            need_post_pass = blur_enabled or color_enabled or (burn_subs and target_ass_path and os.path.exists(target_ass_path))
            if need_post_pass:
                print("[*] VideoMerger: Running Single-Pass Hardware-Accelerated Post-Processing...")
                self._blur_subtitle_region(
                    state,
                    final_output,
                    source_video_for_detection = movie_path,
                    region_pct    = blur_region_pct    if blur_enabled  else 0.0,
                    blur_strength = blur_strength      if blur_enabled  else 0,
                    color_enabled = color_enabled,
                    brightness    = cg_brightness,
                    contrast      = cg_contrast,
                    saturation    = cg_saturation,
                    ass_path      = target_ass_path    if (burn_subs and target_ass_path and os.path.exists(target_ass_path)) else None,
                )
        except Exception as e:
            print(f"[ERROR] VideoMerger: Failed during legacy video merge/writing: {e}")
        finally:
            for clip_obj in [main_video, sfx_only_audio, intro_clip, final_clip]:
                if clip_obj is not None:
                    try: clip_obj.close()
                    except Exception: pass
            for ac in audio_clips:
                try: ac.close()
                except Exception: pass
            for pc in positioned_clips:
                try: pc.close()
                except Exception: pass

        return state

    # ─────────────────────────────────────────────────────
    # WATERMARK GENERATION (Adaptive Contrast)
    # ─────────────────────────────────────────────────────

    def _create_watermark_image(
        self,
        text: str,
        font_size: int = 28,
        opacity: float = 0.85,
        style: str = "badge",
        logo_path: str = ""
    ) -> str:
        """
        Creates a transparent PNG with custom channel branding badge or watermark.
        Styles:
          - 'badge': Sleek dark rounded badge pill with gold/white text for masking underlying watermarks.
          - 'transparent': Simple semi-transparent text with drop shadow.
        """
        from PIL import Image, ImageDraw, ImageFont
        import os
        
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)
        out_path = os.path.join(temp_dir, "watermark.png")
        
        # If logo image file is provided and exists, use it directly
        if logo_path and os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                if opacity < 1.0:
                    alpha = logo_img.split()[3].point(lambda p: int(p * opacity))
                    logo_img.putalpha(alpha)
                logo_img.save(out_path, "PNG")
                return out_path
            except Exception as le:
                print(f"[WARN] VideoMerger: Failed to load logo image {logo_path}: {le}")

        font_found = self._find_myanmar_font()
        try:
            font = ImageFont.truetype(font_found or "arialbd.ttf", font_size)
        except IOError:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except IOError:
                font = ImageFont.load_default()

        # Measure text
        dummy_img = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = max(1, bbox[2] - bbox[0])
            text_height = max(1, bbox[3] - bbox[1])
        except Exception:
            try:
                text_width, text_height = draw.textsize(text, font=font)
            except Exception:
                text_width, text_height = max(1, len(text) * 14), 28

        pad_x = 18
        pad_y = 8
        img_width = text_width + (pad_x * 2)
        img_height = text_height + (pad_y * 2)

        img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if style == "badge":
            # Draw sleek rounded dark pill with border to completely cover source watermark
            radius = min(img_height // 2, 10)
            bg_color = (18, 18, 18, int(230 * opacity))
            border_color = (255, 215, 0, int(200 * opacity)) # Gold accent border
            draw.rounded_rectangle([(0, 0), (img_width - 1, img_height - 1)], radius=radius, fill=bg_color, outline=border_color, width=1)
            # Gold / Pure White text
            text_color = (255, 255, 255, int(255 * opacity))
            draw.text((pad_x, pad_y - 2), text, font=font, fill=text_color)
        else:
            # Transparent shadow style
            shadow_offset = (2, 2)
            shadow_color = (0, 0, 0, int(200 * opacity))
            text_color = (255, 255, 255, int(255 * opacity))
            draw.text((pad_x + shadow_offset[0], pad_y + shadow_offset[1]), text, font=font, fill=shadow_color)
            draw.text((pad_x, pad_y), text, font=font, fill=text_color)

        img.save(out_path, "PNG")
        return out_path

    # ─────────────────────────────────────────────────────
    # MYANMAR SUBTITLE OVERLAY — ASS Generation + FFmpeg Burn
    # ─────────────────────────────────────────────────────

    def _sec_to_ass_ts(self, sec: float) -> str:
        """Convert seconds to ASS timestamp format H:MM:SS.cs (centiseconds)."""
        total_cs = int(round(max(0.0, float(sec)) * 100))
        cs = total_cs % 100
        total_s = total_cs // 100
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _wrap_burmese_text(self, text: str, max_chars: int) -> str:
        """Wrap long Myanmar text into multiple lines at natural syllable/word boundaries (ASS uses {\\N})."""
        text = str(text or "").strip()
        if len(text) <= max_chars:
            return text

        import re
        # Break text into tokens: split by space, but for segments longer than max_chars,
        # perform Myanmar syllable-level segmentation to prevent horizontal screen overflow.
        pattern = re.compile(
            r'[\u1000-\u102a\u104e]'
            r'[\u102b-\u103e\u1036-\u1038]*'
            r'(?:[\u1039][\u1000-\u1021][\u102b-\u103e\u1036-\u1038]*)*'
            r'(?:[\u1000-\u1021][\u103a][\u1037\u1038]*)*'
            r'|[\u1040-\u1049]+'
            r'|[a-zA-Z0-9]+'
            r'|[^\u1000-\u104f\s]'
        )

        words = text.split(" ")
        refined_tokens = []
        for word in words:
            if len(word) <= max_chars:
                refined_tokens.append(word)
            else:
                last_idx = 0
                for m in pattern.finditer(word):
                    if m.start() > last_idx:
                        refined_tokens.append(word[last_idx:m.start()])
                    refined_tokens.append(m.group(0))
                    last_idx = m.end()
                if last_idx < len(word):
                    refined_tokens.append(word[last_idx:])

        lines, current = [], ""
        for tok in refined_tokens:
            if not tok:
                continue
            # Keep punctuation with current line
            if tok in ["၊", "။", ",", ".", "!", "?"] and current:
                current += tok
                continue
            sep = " " if current and not ('\u1000' <= tok[0] <= '\u109F' and '\u1000' <= current[-1] <= '\u109F') else ""
            candidate = current + sep + tok if current else tok
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = tok
        if current:
            lines.append(current)

        return "\\N".join(lines)

    def _chunk_burmese_narration(self, text: str, max_chars_per_chunk: int = 40) -> list:
        """
        Splits narration text into proportional timing chunks.
        Space-agnostic: if the text lacks spaces (standard Myanmar writing),
        segments syllables using Myanmar phonetic boundaries so subtitles are
        never displayed as one giant unchunked sentence.
        """
        text = str(text or "").strip()
        if not text:
            return []

        import re
        syllable_pattern = re.compile(
            r'[\u1000-\u102a\u104e]'
            r'[\u102b-\u103e\u1036-\u1038]*'
            r'(?:[\u1039][\u1000-\u1021][\u102b-\u103e\u1036-\u1038]*)*'
            r'(?:[\u1000-\u1021][\u103a][\u1037\u1038]*)*'
            r'|[\u1040-\u1049]+'
            r'|[a-zA-Z0-9]+'
            r'|[^\u1000-\u104f\s]'
        )

        words = [w for w in text.split(" ") if w]
        refined_tokens = []
        for word in words:
            if len(word) <= max_chars_per_chunk:
                refined_tokens.append(word)
            else:
                last_idx = 0
                for m in syllable_pattern.finditer(word):
                    if m.start() > last_idx:
                        refined_tokens.append(word[last_idx:m.start()])
                    refined_tokens.append(m.group(0))
                    last_idx = m.end()
                if last_idx < len(word):
                    refined_tokens.append(word[last_idx:])

        if not refined_tokens:
            refined_tokens = [text]

        chunks = []
        current = ""
        for tok in refined_tokens:
            if not tok:
                continue
            if tok in ["၊", "။", ",", ".", "!", "?"] and current:
                current += tok
                continue
            sep = " " if current and not ('\u1000' <= tok[0] <= '\u109F' and '\u1000' <= current[-1] <= '\u109F') else ""
            candidate = current + sep + tok if current else tok
            if len(candidate) <= max_chars_per_chunk:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = tok
        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    def _write_ass(
        self,
        timings: list,
        ass_path: str,
        font_name: str    = "Myanmar Text",
        font_size: int    = 40,
        bold: bool        = True,
        border_style: int = 3,
        outline_width: int = 3,
        margin_bottom: int = 50,
        max_chars: int    = 28,
        preset: str       = None,
    ) -> str:
        """
        Write an ASS (Advanced SubStation Alpha) subtitle file.
        All styling is embedded — no FFmpeg force_style needed.
        ASS colour: &HAABBGGRR (alpha 00=opaque, 80=50% transparent)
        BorderStyle=1: outline+shadow  |  BorderStyle=3: opaque box background
        """
        bold_flag = "-1" if bold else "0"

        # Resolve style preset from SUBTITLE_PRESETS if provided
        shadow_val = 2
        primary_colour = "&H00FFFFFF"
        outline_colour = "&H00000000"

        if preset:
            from brain.config import SUBTITLE_PRESETS
            p_data = SUBTITLE_PRESETS.get(str(preset).lower())
            if p_data:
                font_size = int(p_data.get("font_size", font_size))
                bold_flag = "-1" if p_data.get("bold", bold) else "0"
                border_style = int(p_data.get("border_style", border_style))
                outline_val = int(p_data.get("outline_width", outline_width))
                shadow_val = int(p_data.get("shadow", 2))
                primary_colour = p_data.get("primary_color", "&H00FFFFFF")
                outline_colour = p_data.get("outline_color", "&H00000000")
                back_colour = p_data.get("back_color", "&HB0000000")
                margin_bottom = int(p_data.get("margin_bottom", margin_bottom))
            elif border_style == 3:
                outline_val = 10
                back_colour = "&HB0000000"
            else:
                outline_val = outline_width
                back_colour = "&H90000000"
        elif border_style == 3:
            # Box background mode (YouTube-style): Outline=box_padding, Shadow for depth
            outline_val = 10      # box padding in px
            shadow_val  = 2       # subtle depth shadow
            back_colour = "&HB0000000"   # 70% opacity deep dark box for maximum contrast
        else:
            # Classic outline mode
            outline_val = outline_width
            shadow_val  = 2
            back_colour = "&H90000000"

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "WrapStyle: 0\n"
            "PlayResX: 1920\n"
            "PlayResY: 1080\n"
            "Collisions: Normal\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{font_name},{font_size},"
            f"{primary_colour},&H000000FF,{outline_colour},{back_colour},"
            f"{bold_flag},0,0,0,100,100,0,0,{border_style},{outline_val},{shadow_val},"
            f"2,10,10,{margin_bottom},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        dialogue_lines = []
        for (start_sec, duration, text) in timings:
            if not text:
                continue
            text = text.strip()

            # Split long narration into proportional chunks using syllable awareness
            chunks = self._chunk_burmese_narration(text, max_chars_per_chunk=max_chars * 2)
            if not chunks:
                continue

            seg_dur = duration / len(chunks)
            for i, chunk in enumerate(chunks):
                seg_start = start_sec + i * seg_dur
                seg_end   = seg_start + seg_dur - 0.05
                # BUG-M7 Fix: Escape ASS special chars { } to prevent format code injection
                safe_chunk = chunk.replace('\\', '').replace('{', '').replace('}', '')
                ass_text  = self._wrap_burmese_text(safe_chunk, max_chars)
                ts_start  = self._sec_to_ass_ts(seg_start)
                ts_end    = self._sec_to_ass_ts(seg_end)
                dialogue_lines.append(
                    f"Dialogue: 0,{ts_start},{ts_end},Default,,0,0,0,,{ass_text}"
                )

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(dialogue_lines) + "\n")

        print(f"[*] MyanmarSubs: ASS written → {ass_path} ({len(dialogue_lines)} subtitle entries)")
        return ass_path

    def _find_myanmar_font(self) -> str:
        """Find a suitable Myanmar Unicode font path for reference/logging."""
        candidates = [
            r"assets\fonts\NotoSansMyanmar-Regular.ttf",
            r"assets/fonts/NotoSansMyanmar-Regular.ttf",
            # Windows fonts
            r"C:\Windows\Fonts\mmrtext.ttf",     # Myanmar Text (Win10+)
            r"C:\Windows\Fonts\mmrtextb.ttf",
            r"C:\Windows\Fonts\NotoSansMyanmar-Regular.ttf",
            r"C:\Windows\Fonts\Padauk-Regular.ttf",
            # Linux (Colab, Kaggle, Docker) fonts
            "/usr/share/fonts/truetype/padauk/Padauk-Regular.ttf",
            "/usr/share/fonts/truetype/padauk/Padauk.ttf",
            "/usr/share/fonts/truetype/padauk/Padauk-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansMyanmar-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansMyanmar-Bold.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansMyanmar-Regular.otf",
        ]
        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        return None

    def _export_standalone_srt(self, timings: list, output_dir: str):
        """Exports standalone .srt and .ass subtitle files for YouTube caption upload / VLC player."""
        if not timings:
            return
        srt_path = os.path.join(output_dir, "myanmar_subs.srt")
        ass_path = os.path.join(output_dir, "myanmar_subs.ass")

        def _sec_to_srt_ts(sec: float) -> str:
            total_ms = int(round(max(0.0, float(sec)) * 1000))
            ms = total_ms % 1000
            total_s = total_ms // 1000
            s = total_s % 60
            total_m = total_s // 60
            m = total_m % 60
            h = total_m // 60
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        lines = []
        idx = 1
        for item in timings:
            try:
                start_s = float(item[0])
                dur_s = float(item[1])
                txt = str(item[2]).strip()
                if not txt:
                    continue
                end_s = start_s + dur_s
                lines.append(f"{idx}\n{_sec_to_srt_ts(start_s)} --> {_sec_to_srt_ts(end_s)}\n{txt}\n")
                idx += 1
            except Exception:
                pass

        if lines:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            print(f"[OK] VideoMerger: Standalone SRT subtitles exported -> {srt_path}")

        # Also write clean ASS file
        try:
            import sys
            font_name = "Myanmar Text" if sys.platform == "win32" else "Padauk"
            self._write_ass(timings, ass_path, font_name=font_name, font_size=40, bold=True, border_style=3, outline_width=3, margin_bottom=50, max_chars=28)
        except Exception:
            pass



    # ─────────────────────────────────────────────────────
    # SUBTITLE BLUR — Vision AI Auto-Detection + FFmpeg Pass
    # ─────────────────────────────────────────────────────

    def _detect_subtitle_region_with_vision(self, video_path: str, state: MovieState = None):
        """
        Uses Gemini Vision AI to analyze sample frames from the ORIGINAL SOURCE video
        and detect the EXACT vertical region (start_y_pct, height_pct) where
        hardcoded subtitles appear.
        Samples frames at Whisper dialogue timestamps to guarantee subtitle visibility.

        Returns:
            (start_y_pct, height_pct, subtitle_found)
        """
        import os, cv2, json
        from brain.gemini_client import call_gemini_vision
        import brain.config as cfg

        print(f"[*] VisionAI Subtitle Detector: Analyzing source video for subtitles: {os.path.basename(video_path)}")
        temp_dir = os.path.join("temp", "sub_detect")
        os.makedirs(temp_dir, exist_ok=True)

        default_start_y = 0.82
        default_height  = 0.18

        try:
            config_data = cfg.load_config()
            gemini_cfg = config_data.get("gemini", {})
            api_keys = gemini_cfg.get("api_keys", [])
            model = gemini_cfg.get("model", "gemini-3.5-flash-lite")

            prompt = (
                "Analyze this video frame carefully. Look at the lower half of the frame (bottom 50%). "
                "Are there any hardcoded DIALOGUE subtitles or captions? "
                "IGNORE watermarks, channel logos, or title cards at the top or middle of the screen. "
                "Respond ONLY in valid JSON with NO markdown formatting: "
                '{"has_subtitles": true, "start_y_pct": 0.75, "height_pct": 0.12} '
                "where start_y_pct (0.0=top, 1.0=bottom) is where the dialogue text STARTS, "
                "and height_pct is the vertical height of the text region. "
                "If no dialogue subtitles exist in the lower half, respond: "
                '{"has_subtitles": false, "start_y_pct": 0.82, "height_pct": 0.18}'
            )

            def get_sample_frames(pcts, stage_prefix):
                frames = []
                cap = cv2.VideoCapture(video_path)
                try:
                    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 300)
                    
                    dialogue_times = []
                    if state and getattr(state, "transcript", None):
                        for s in state.transcript[:15]:
                            t_val = getattr(s, "start", None) if hasattr(s, "start") else s.get("start") if isinstance(s, dict) else None
                            if t_val is not None and float(t_val) > 1.0:
                                dialogue_times.append(float(t_val) + 0.5)

                    if dialogue_times and stage_prefix == "s1":
                        step = max(1, len(dialogue_times) // 5)
                        for idx, sec in enumerate(dialogue_times[::step][:5]):
                            frame_idx = min(int(sec * fps), total_frames - 1)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                frame_path = os.path.join(temp_dir, f"frame_dialogue_{idx}_{int(sec)}s.jpg")
                                cv2.imwrite(frame_path, frame)
                                frames.append(frame_path)

                    if not frames:
                        for sample_pct in pcts:
                            sample_frame_idx = int(total_frames * sample_pct)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, sample_frame_idx)
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                frame_path = os.path.join(temp_dir, f"frame_{stage_prefix}_{int(sample_pct*100):03d}.jpg")
                                cv2.imwrite(frame_path, frame)
                                frames.append(frame_path)
                finally:
                    cap.release()
                return frames

            def scan_frames(sample_frames, stage_name):
                print(f"[*] VisionAI Subtitle Detector ({stage_name}): Analyzing {len(sample_frames)} frames...")
                results = []
                for i, frame_path in enumerate(sample_frames):
                    try:
                        res_text, used_model = call_gemini_vision(
                            system_prompt=(
                                "You are a precise computer vision AI. Your job is to detect ANY text, "
                                "subtitles, captions, or overlaid text in video frames. "
                                "Look at the ENTIRE frame carefully. Respond ONLY in valid JSON."
                            ),
                            user_text=prompt,
                            image_path=frame_path,
                            api_key=api_keys,
                            model=model,
                            temperature=0.05
                        )
                        clean_json = res_text.strip().strip("`").replace("json", "").strip()
                        parsed = json.loads(clean_json)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            parsed = parsed[0]
                        elif not isinstance(parsed, dict):
                            parsed = {}
                            
                        results.append(parsed)
                        found = parsed.get("has_subtitles", False)
                        print(f"[*] VisionAI [{stage_name}] Frame {i+1}/{len(sample_frames)}: has_subtitles={found} "
                              f"y={parsed.get('start_y_pct', '?')} h={parsed.get('height_pct', '?')} (model: {used_model})")
                    except Exception as e:
                        print(f"[WARN] VisionAI [{stage_name}] Frame {i+1} failed: {e}")
                        continue
                return results

            # Stage 1: Scan first 50% of the video (5%, 15%, 25%, 35%, 50%)
            stage1_frames = get_sample_frames([0.05, 0.15, 0.25, 0.35, 0.50], "s1")
            if not stage1_frames:
                print("[WARN] VisionAI Subtitle Detector: Could not read any frame. Skipping blur.")
                return default_start_y, default_height, False

            detection_results = scan_frames(stage1_frames, "Stage 1 (0-50%)")
            frames_with_subs = [r for r in detection_results if r.get("has_subtitles", False)]

            # Stage 2 Fallback: If no subtitles found in first 50%, scan second half (60%, 70%, 80%, 90%)
            if not frames_with_subs:
                print("[*] VisionAI Stage 1 (0-50%) found NO subtitles. Triggering Stage 2: Scanning remaining 50-90% of video...")
                stage2_frames = get_sample_frames([0.60, 0.70, 0.80, 0.90], "s2")
                if stage2_frames:
                    stage2_results = scan_frames(stage2_frames, "Stage 2 (50-90%)")
                    detection_results.extend(stage2_results)
                    frames_with_subs = [r for r in detection_results if r.get("has_subtitles", False)]

            if not detection_results:
                print("[WARN] VisionAI: All frame analyses failed. Skipping blur.")
                return default_start_y, default_height, False

            # Filter out false positives (e.g., watermarks at the top of the screen)
            # Dialogue subtitles are almost always in the lower half (y >= 0.5)
            valid_subs = []
            for r in frames_with_subs:
                try:
                    raw_y = r.get("start_y_pct", r.get("y", default_start_y))
                    raw_h = r.get("height_pct", r.get("h", default_height))
                    y_val = float(raw_y)
                    h_val = float(raw_h)
                    # Normalize if returned as raw pixel value (e.g. 743px for 1080p frame)
                    if y_val > 1.0:
                        y_val = y_val / 1080.0
                    if h_val > 1.0:
                        h_val = h_val / 1080.0
                    
                    y_val = max(0.0, min(0.98, y_val))
                    h_val = max(0.02, min(0.40, h_val))
                    if y_val >= 0.5:
                        valid_subs.append({"start_y_pct": y_val, "height_pct": h_val})
                except Exception:
                    continue
            
            subtitle_found = len(valid_subs) > 0

            if subtitle_found:
                import statistics
                y_values = [float(r["start_y_pct"]) for r in valid_subs]
                h_values = [float(r["height_pct"]) for r in valid_subs]
                
                # Use median to ignore extreme outliers instead of average
                median_y = statistics.median(y_values)
                max_h = max(h_values)  # Use max height to ensure we cover 2-line subtitles if detected
                
                y_start  = max(0.50, min(0.92, median_y - 0.02))
                y_height = max(0.05, min(1.0 - y_start, max_h + 0.04))

                print(
                    f"[OK] VisionAI: Subtitles CONFIRMED ({len(valid_subs)}/{len(detection_results)} frames positive)! "
                    f"Region -> Y: {y_start*100:.1f}%, Height: {y_height*100:.1f}% — Will blur."
                )
                return y_start, y_height, True
            else:
                print(f"[*] VisionAI: No subtitles detected across ENTIRE video ({len(detection_results)} frames tested). Skipping blur.")
                return default_start_y, default_height, False

        except Exception as e:
            print(f"[WARN] VisionAI Subtitle Detector: Detection failed ({e}). Skipping blur to be safe.")
            return default_start_y, default_height, False
        finally:
            # Clean up temp frames
            import shutil
            if os.path.exists(temp_dir):
                try: shutil.rmtree(temp_dir)
                except Exception: pass

    def _blur_subtitle_region(
        self,
        state: MovieState,
        video_path: str,
        source_video_for_detection: str = None,
        region_pct: float = 0.18,
        blur_strength: int = 18,
        color_enabled: bool = False,
        brightness: float = 0.03,
        contrast: float = 1.02,
        saturation: float = 1.08,
        ass_path: str = None,
    ):
        """
        Unified single FFmpeg post-pass that combines up to three post-processing operations:

        Layer 1 — Vision AI Powered Subtitle Blur:
          Uses Gemini Vision AI to detect exact subtitle Y-boundaries from the
          ORIGINAL SOURCE movie (not the recap), crops that exact region,
          applies boxblur, and overlays back. Skipped if AI says no subtitles.

        Layer 2 — Color Grading (eq filter):
          Applies slight brightness / contrast / saturation shift via FFmpeg.

        Layer 3 — Myanmar Subtitle Burn (ASS filter):
          Burns styled Myanmar ASS subtitles in the SAME encode pass.
        Hardware-accelerated via Intel QSV / NVIDIA NVENC with automatic libx264 CPU fallback.
        """
        import subprocess, os

        ffmpeg_bin = _get_ffmpeg_bin()
        if not ffmpeg_bin:
            print("[WARN] PostProcess: ffmpeg not found. Skipping post-pass.")
            return

        do_blur  = blur_strength > 0
        do_color = color_enabled
        do_subtitles = bool(ass_path and os.path.exists(ass_path))

        user_sub_mode = getattr(state, "subtitle_mode", "auto") if state is not None else "auto"
        user_sub_mode = user_sub_mode or "auto"

        if user_sub_mode == "no":
            print("[*] Subtitle Blur: Disabled by user setting ('No Subtitles'). Skipping blur pass.")
            do_blur = False

        # Run Vision AI on ORIGINAL MOVIE to get exact subtitle coordinates
        # (The recap output does NOT have subtitles — always analyze the source)
        start_y_pct, height_pct = 0.82, 0.18
        subtitle_found = False
        if do_blur:
            detect_target = source_video_for_detection if source_video_for_detection and os.path.exists(source_video_for_detection) else video_path

            if user_sub_mode == "yes":
                print("[*] Subtitle Blur: User selected 'Has Subtitles' — Forcing subtitle blur mode on.")
                y, h, found = self._detect_subtitle_region_with_vision(detect_target, state=state)
                start_y_pct = y if found else 0.82
                height_pct = h if found else 0.18
                subtitle_found = True
            else:
                cache = getattr(state, "subtitle_detection", None) if state is not None else None
                # Only reuse cache if it previously FOUND subtitles
                # If cache says no subtitles, always re-detect (Gemini may have been wrong)
                cache_valid = (
                    cache
                    and cache.get("video_path") == os.path.abspath(detect_target)
                    and cache.get("has_subtitles", False) is True  # Only trust positive cache
                )
                if cache_valid:
                    start_y_pct = float(cache.get("start_y_pct", start_y_pct))
                    height_pct = float(cache.get("height_pct", height_pct))
                    subtitle_found = True
                    print("[*] VideoMerger: Reusing cached subtitle detection (subtitles confirmed previously).")
                else:
                    if cache and not cache.get("has_subtitles", False):
                        print("[*] VideoMerger: Previous detection found no subtitles — re-running with improved detector...")
                    start_y_pct, height_pct, subtitle_found = self._detect_subtitle_region_with_vision(detect_target, state=state)
                if state is not None:
                    state.subtitle_detection = {
                        "video_path": os.path.abspath(detect_target),
                        "has_subtitles": subtitle_found,
                        "start_y_pct": start_y_pct,
                        "height_pct": height_pct,
                    }
                if not subtitle_found:
                    print("[*] PostProcess: No subtitles detected in source — skipping blur pass.")
                    do_blur = False

        if not do_blur and not do_color and not do_subtitles:
            print("[*] PostProcess: No blur, color grade, or subtitles requested. Skipping post-processing pass.")
            return

        if do_blur:
            start_y_pct = max(0.0, min(float(start_y_pct), 0.95))
            height_pct = max(0.02, min(float(height_pct), 1.0 - start_y_pct))

        steps = []
        if do_blur:      steps.append(f"VisionAI subtitle blur (Y-start={start_y_pct*100:.1f}%, h={height_pct*100:.1f}%, r={blur_strength})")
        if do_color:     steps.append(f"color grade (b={brightness:+.2f}, c={contrast:.2f}, s={saturation:.2f}), dynamic noise, vignette")
        if do_subtitles: steps.append(f"Myanmar ASS subtitles burn ({os.path.basename(ass_path)})")
        print(f"[*] PostProcess: Applying unified single-pass — {', '.join(steps)}")

        base, ext = os.path.splitext(video_path)
        tmp_path  = base + "_posttmp" + ext

        # ── Build filter_complex ─────────────────────────────────────────
        # Step 1: Fix even dimensions
        base_filter = "crop=w='trunc(iw/2)*2':h='trunc(ih/2)*2'"

        if do_blur:
            r = blur_strength
            # Guarantee even integer pixel boundaries for libx264 / yuv420p encoder
            flt = (
                f"[0:v]{base_filter},split=2[orig][sub];"
                f"[sub]crop=iw:'trunc(ih*{height_pct:.3f}/2)*2':0:'trunc(ih*{start_y_pct:.3f}/2)*2',"
                f"boxblur=luma_radius={r}:luma_power=2"
                f":chroma_radius={max(1,r//2)}:chroma_power=2[blurred];"
                f"[orig][blurred]overlay=0:'trunc(H*{start_y_pct:.3f}/2)*2'[blended]"
            )
            last_out = "[blended]"
        else:
            flt = f"[0:v]{base_filter}[blended]"
            last_out = "[blended]"

        if do_color:
            eq_str = (
                f"eq=brightness={brightness:.3f}"
                f":contrast={contrast:.3f}"
                f":saturation={saturation:.3f}"
                f",noise=alls=2:allf=t"       # Dynamic Film Grain
                f",vignette=PI/4"             # Subtle Edge Darkening
            )
            flt += f";{last_out}{eq_str}[graded]"
            last_out = "[graded]"

        working_dir = None
        if do_subtitles:
            ass_basename = os.path.basename(ass_path)
            working_dir = os.path.dirname(os.path.abspath(ass_path))
            flt += f";{last_out}ass={ass_basename}[subbed]"
            last_out = "[subbed]"

        # Map last output label
        filter_args = ["-filter_complex", flt, "-map", last_out]

        enc_info = detect_hardware_encoder()
        codec = enc_info.get("codec", "libx264")
        preset = enc_info.get("preset", "faster")

        quality_args = ["-b:v", "6M", "-maxrate", "9M", "-bufsize", "12M"] if enc_info.get("type") == "gpu" else ["-crf", "20"]
        cmd = [
            ffmpeg_bin, "-y",
            "-i", os.path.abspath(video_path),
            *filter_args,
            "-map", "0:a?",
            "-c:v", codec,
            "-preset", preset,
            *quality_args,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "copy",
            os.path.abspath(tmp_path),
        ]

        # Dynamically scale timeout to allow ample time for full movies
        dur_sec = getattr(state, "duration_sec", 0.0) if state else 0.0
        if not dur_sec and state and getattr(state, "duration", None):
            try:
                parts = str(state.duration).split(":")
                if len(parts) == 3:
                    dur_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                dur_sec = 600.0
        dyn_timeout = max(1200, int((dur_sec or 600.0) * 2.5))

        try:
            print(f"[*] PostProcess: Encoding with {enc_info.get('label', codec)} [{codec}]...")
            result = subprocess.run(
                cmd, cwd=working_dir, capture_output=True, text=True, timeout=dyn_timeout,
                encoding="utf-8", errors="replace"
            )
            if result.returncode != 0 and codec != "libx264":
                print(f"[WARN] PostProcess: Hardware encoder '{codec}' failed. Retrying with CPU libx264...")
                fallback_cmd = list(cmd)
                if codec in fallback_cmd:
                    fallback_cmd[fallback_cmd.index(codec)] = "libx264"
                if preset in fallback_cmd:
                    fallback_cmd[fallback_cmd.index(preset)] = "superfast"
                if "-b:v" in fallback_cmd:
                    b_idx = fallback_cmd.index("-b:v")
                    fallback_cmd = fallback_cmd[:b_idx] + ["-crf", "20"] + fallback_cmd[b_idx+6:]
                result = subprocess.run(
                    fallback_cmd, cwd=working_dir, capture_output=True, text=True, timeout=dyn_timeout,
                    encoding="utf-8", errors="replace"
                )

            if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100_000:
                os.replace(tmp_path, video_path)
                if do_subtitles and state is not None:
                    state.subtitles_burned = True
                print("[OK] PostProcess: Copyright-safe single-pass post-processing complete!")
            else:
                print(f"[WARN] PostProcess: FFmpeg returned exit code {result.returncode}.")
                if result.stderr:
                    print(f"[WARN] FFmpeg stderr: {result.stderr[-400:]}")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except subprocess.TimeoutExpired:
            print("[WARN] PostProcess: FFmpeg timed out. Original video kept.")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except Exception: pass
        except Exception as e:
            print(f"[WARN] PostProcess: {e}. Original video kept.")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except Exception: pass

    def generate_reels_video(
        self,
        source_video_path: str,
        output_dir: str,
        hook_title: str = "",
        subtitle_timings: list = None,
        duration_sec: float = 600.0,
        subtitle_mode: str = None,
        resolution: str = None,
        preset: str = None,
        state: MovieState = None,
    ) -> str | None:
        """
        Exports a dedicated 9:16 Vertical Video for Facebook Reels, TikTok, and Shorts.
        Layout (The 'Viral Recap Frame'):
          - Top 20%: Catchy golden Burmese Hook Title.
          - Middle 55%: Uncropped, high-quality 16:9 recap video centered over blurred dynamic video background.
          - Bottom 25%: Facebook Safe Zone for Myanmar ASS subtitles, well above bottom UI controls.
        Hardware-accelerated via NVENC on Colab or QSV/libx264 on PC.
        Supports 1080p (1080x1920) or 720p (720x1280) presets and hardsub on/off toggle.
        """
        import sys, subprocess, shutil

        if not os.path.exists(source_video_path):
            print(f"[WARN] ReelsExporter: Source video not found: {source_video_path}")
            return None

        os.makedirs(output_dir, exist_ok=True)
        reels_output = os.path.join(output_dir, "final_reels.mp4")
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)

        config_data = cfg.load_config()
        reels_cfg = config_data.get("reels", {})
        if not reels_cfg.get("enabled", True):
            print("[*] ReelsExporter: Disabled in config.json -> reels.enabled = false")
            return None

        sub_mode = str(subtitle_mode or self.subtitle_mode or "burn").lower()
        res_mode = str(resolution or self.resolution or "1080p").lower()

        if res_mode == "720p":
            w_target = 720
            h_target = 1280
            hook_fontsize = 36
            sub_fontsize = 30
            safe_margin = 110
        else:
            w_target = int(reels_cfg.get("width", 1080))
            h_target = int(reels_cfg.get("height", 1920))
            hook_fontsize = 52
            sub_fontsize = 44
            safe_margin = int(reels_cfg.get("safe_zone_margin", 160))

        font_name = "Myanmar Text" if sys.platform == "win32" else "Padauk"
        font_found = self._find_myanmar_font()
        if font_found and os.path.exists(font_found):
            base_font = os.path.splitext(os.path.basename(font_found))[0]
            if "padauk" in base_font.lower():
                font_name = "Padauk"
            elif "mmrtext" in base_font.lower() or "myanmar" in base_font.lower():
                font_name = "Myanmar Text"

        # 1. Create Reels ASS Subtitle & Hook Title File with unique filename to prevent batch collision
        import uuid
        safe_reels_id = _get_safe_ascii_id(source_video_path, prefix="reels")
        ass_path = os.path.join(temp_dir, f"reels_subs_{safe_reels_id}_{uuid.uuid4().hex[:6]}.ass")
        title_clean = str(hook_title or "").replace("|", "-").strip()
        if not title_clean:
            title_clean = "Movie Recap"
        # Truncate title if extremely long
        if len(title_clean) > 80:
            title_clean = title_clean[:77] + "..."

        # Word wrap title for 1080px portrait canvas (approx 20-22 chars per line) using syllable awareness
        wrapped_title = self._wrap_burmese_text(title_clean, max_chars=20).replace("{\\N}", "\\N")

        # Generate ASS with three styles:
        # Style 1: ReelsBrand (Top Header Badge on Canvas, White/Gold with Dark Pill, MarginV=45)
        # Style 2: ReelsHook (Top Center, Gold/Yellow, Big, MarginV=110)
        # Style 3: ReelsSubs (Bottom Center Safe Zone, styled according to chosen preset)
        wm_cfg = config_data.get("watermark", {})
        wm_override = getattr(state, "watermark_override", {}) or {}
        wm_brand_enabled = wm_override.get("enabled", wm_cfg.get("enabled", True))
        wm_brand_text = wm_override.get("text") or wm_cfg.get("text", "Pai Ai Movie Studio")

        # Resolve subtitle preset for Reels
        sub_cfg = config_data.get("subtitle_overlay", {})
        sub_preset = preset or getattr(state, "subtitle_style_preset", None) or sub_cfg.get("style_preset", "box_black")
        from brain.config import SUBTITLE_PRESETS
        p_data = SUBTITLE_PRESETS.get(str(sub_preset).lower(), {})
        reels_sub_border = int(p_data.get("border_style", 3))
        reels_sub_outline = int(p_data.get("outline_width", 10 if reels_sub_border == 3 else 4))
        reels_sub_shadow = int(p_data.get("shadow", 2))
        reels_sub_primary = p_data.get("primary_color", "&H00FFFFFF")
        reels_sub_outline_col = p_data.get("outline_color", "&H00000000")
        reels_sub_back = p_data.get("back_color", "&HB0000000")
        
        hook_end_s = "9:59:59.99"
        if getattr(state, "outro_card", False) or getattr(state, "outro_card_applied", False):
            # End top hook title 3s before video finishes so outro card is displayed cleanly
            src_dur = 0.0
            try:
                import cv2
                cap = cv2.VideoCapture(source_video_path)
                frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                if fps > 0:
                    src_dur = frames / fps
                cap.release()
            except Exception:
                pass
            if src_dur > 5.0:
                movie_end = max(1.0, src_dur - 3.0)
                h = int(movie_end // 3600)
                m = int((movie_end % 3600) // 60)
                s = movie_end % 60
                hook_end_s = f"{h}:{m:02d}:{s:05.2f}"

        brand_events = [f"Dialogue: 0,0:00:00.00,{hook_end_s},ReelsBrand,,0,0,0,,🎬 {wm_brand_text}"] if wm_brand_enabled else []
        hook_events = [f"Dialogue: 0,0:00:00.00,{hook_end_s},ReelsHook,,0,0,0,,{wrapped_title}"]
        events_str = "\n".join(brand_events + hook_events)

        ass_content = f"""[Script Info]
Title: Facebook Reels Canvas Overlay
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {w_target}
PlayResY: {h_target}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ReelsBrand,{font_name},32,&H00FFFFFF,&H00000000,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,8,2,8,40,40,45,1
Style: ReelsHook,{font_name},{hook_fontsize},&H0000D7FF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,3,8,40,40,110,1
Style: ReelsSubs,{font_name},{sub_fontsize},{reels_sub_primary},&H00000000,{reels_sub_outline_col},{reels_sub_back},-1,0,0,0,100,100,0,0,{reels_sub_border},{reels_sub_outline},{reels_sub_shadow},2,40,40,{safe_margin + 120},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events_str}
"""
        burn_reels_subs = sub_mode not in ["none", "off", "no"]
        is_clean_source = "_clean" in os.path.basename(source_video_path).lower()
        if not is_clean_source and burn_reels_subs:
            # If source video is already hard-subbed (e.g. fallback when clean video was deleted),
            # prevent burning duplicate overlapping subtitles
            if getattr(state, "subtitles_burned", False):
                print("[*] ReelsExporter: Source video already contains burned subtitles. Skipping duplicate subtitle burn.")
                burn_reels_subs = False

        thumb_offset = 0.0
        if getattr(state, "thumbnail_intro_applied", None) is not None:
            if state.thumbnail_intro_applied:
                thumb_cfg = config_data.get("thumbnail_intro", {})
                thumb_offset = float(thumb_cfg.get("duration_sec", 3.0))
        elif getattr(state, "thumbnail_intro_enabled", False):
            src_dur = 0.0
            try:
                import cv2
                cap = cv2.VideoCapture(source_video_path)
                frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                if fps > 0:
                    src_dur = frames / fps
                cap.release()
            except Exception:
                pass
            orig_dur = getattr(state, "duration_sec", 0.0) or 0.0
            thumb_cfg = config_data.get("thumbnail_intro", {})
            thumb_dur = float(thumb_cfg.get("duration_sec", 3.0))
            if orig_dur > 0 and src_dur >= orig_dur + (thumb_dur * 0.5):
                thumb_offset = thumb_dur

        if burn_reels_subs and subtitle_timings:
            for item in subtitle_timings:
                try:
                    start_s = float(item[0]) + thumb_offset
                    dur_s   = float(item[1])
                    raw_txt = str(item[2]).strip()
                    if not raw_txt: continue
                    chunks = self._chunk_burmese_narration(raw_txt, max_chars_per_chunk=72)
                    if not chunks: continue
                    seg_dur = dur_s / len(chunks)
                    for i, chunk in enumerate(chunks):
                        seg_start = start_s + i * seg_dur
                        seg_end   = seg_start + seg_dur - 0.05
                        safe_chunk = chunk.replace('\\', '').replace('{', '').replace('}', '').strip()
                        if not safe_chunk: continue
                        ass_text  = self._wrap_burmese_text(safe_chunk, max_chars=24)
                        t_start   = self._sec_to_ass_ts(seg_start)
                        t_end     = self._sec_to_ass_ts(seg_end)
                        ass_content += f"Dialogue: 1,{t_start},{t_end},ReelsSubs,,0,0,0,,{ass_text}\n"
                except Exception:
                    pass

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # 2. Build FFmpeg Filter Graph:
        ffmpeg_bin = _get_ffmpeg_bin()
        enc_info = detect_hardware_encoder()
        abs_src = os.path.abspath(source_video_path)
        ass_basename = os.path.basename(ass_path)
        temp_reels_out = os.path.join(temp_dir, "temp_reels_render.mp4")

        # 16x faster silky bokeh background: downscale to 270x480, blur lightly, then upscale
        bg_w = w_target // 4
        bg_h = h_target // 4

        # 30 FPS Cap: Reels, TikTok & Shorts are natively 30 FPS
        src_info = _get_video_info(source_video_path)
        reels_fps = src_info.get("fps", 30.0)
        reels_fps_cap = "fps=30," if float(reels_fps) > 32.0 else ""

        # Scale movie foreground to canvas width cleanly across any input resolution
        filter_complex = (
            f"[0:v]{reels_fps_cap}scale={bg_w}:{bg_h}:force_original_aspect_ratio=increase,"
            f"crop={bg_w}:{bg_h},boxblur=12:3,"
            f"scale={w_target}:{h_target}[bg];"
            f"[0:v]{reels_fps_cap}scale={w_target}:-2[fg];"
            f"[bg][fg]overlay=0:({h_target}-h)/2,"
            f"ass={ass_basename}[out]"
        )

        codec = enc_info["codec"]
        preset = enc_info.get("preset", "veryfast")
        quality_args = ["-b:v", "6M", "-maxrate", "9M", "-bufsize", "12M"] if enc_info["type"] == "gpu" else ["-crf", "20"]
        cmd = [
            ffmpeg_bin, "-y",
            "-i", abs_src,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", codec,
            "-preset", preset,
            *quality_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            temp_reels_out
        ]

        print(f"[*] ReelsExporter: Rendering 9:16 Canvas Reels ({w_target}x{h_target}) using {enc_info['label']} [{codec}]...")
        timeout_sec = max(3600, int((duration_sec or 600.0) * 4.0))
        try:
            res = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_sec)
            if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                print("\n🛑 [STOP] ReelsExporter: FFmpeg cancelled by user.")
                raise InterruptedError("Reels rendering was cancelled by user.")
            if res.returncode == 0 and os.path.exists(temp_reels_out) and os.path.getsize(temp_reels_out) > 10_000:
                shutil.move(temp_reels_out, reels_output)
                print(f"🎉 [OK] ReelsExporter: Successfully created 9:16 Facebook Reels video -> {reels_output}")
                return reels_output
            else:
                err_msg = (res.stderr or "")[-500:]
                print(f"[WARN] ReelsExporter: Hardware encoding/filter failed (code={res.returncode}, {err_msg}). Retrying with CPU fallback...")
                
                # Fallback: Retry with libx264 and clean canvas (overlay only, safe against missing libass)
                clean_filter = (
                    f"[0:v]scale={bg_w}:{bg_h}:force_original_aspect_ratio=increase,"
                    f"crop={bg_w}:{bg_h},boxblur=12:3,"
                    f"scale={w_target}:{h_target}[bg];"
                    f"[0:v]scale={w_target}:-2[fg];"
                    f"[bg][fg]overlay=0:({h_target}-h)/2[out]"
                )
                cmd_fallback = [
                    ffmpeg_bin, "-y",
                    "-i", abs_src,
                    "-filter_complex", clean_filter,
                    "-map", "[out]",
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    temp_reels_out
                ]
                res2 = subprocess.run(cmd_fallback, cwd=temp_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_sec)
                if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                    print("\n🛑 [STOP] ReelsExporter: FFmpeg CPU fallback cancelled by user.")
                    raise InterruptedError("Reels rendering was cancelled by user.")
                if res2.returncode == 0 and os.path.exists(temp_reels_out) and os.path.getsize(temp_reels_out) > 10_000:
                    shutil.move(temp_reels_out, reels_output)
                    print(f"🎉 [OK] ReelsExporter: Created 9:16 Reels video via fallback -> {reels_output}")
                    return reels_output
                else:
                    print(f"[ERROR] ReelsExporter failed completely: {(res2.stderr or '')[-400:]}")
                    return None
        except InterruptedError:
            raise
        except Exception as e:
            print(f"[ERROR] ReelsExporter encountered error: {e}")
            return None
        finally:
            if os.path.exists(temp_reels_out):
                try: os.remove(temp_reels_out)
                except Exception: pass



