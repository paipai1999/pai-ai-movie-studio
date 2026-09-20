import argparse
import os
import sys
import shutil
from agents.master import MasterAgent
from agents.downloader_agent import DownloaderAgent
from brain.planner import BatchProcessor
from brain import config as cfg

# Force UTF-8 output on Windows to prevent emoji/Unicode encode errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ASCII_ART = r"""
  __  __            _        _____                       
 |  \/  |          (_)      |  __ \                      
 | \  / | _____   ___  ___  | |__) |___  ___ __ _ _ __   
 | |\/| |/ _ \ \ / / |/ _ \ |  _  // _ \/ __/ _` | '_ \  
 | |  | | (_) \ V /| |  __/ | | \ \  __/ (_| (_| | |_) | 
 |_|  |_|\___/ \_/ |_|\___| |_|  \_\___|\___\__,_| .__/  
                                                  |_|     
  100% Free Local AI Pipeline  .  Cost = $0              
"""

def setup_directories():
    for d in ["movies", "outputs", "temp", "voiceover", "assets/voices", "assets/bgm"]:
        os.makedirs(d, exist_ok=True)

def run_interactive_cleanup():
    print("\n=== 🗑️ MOVIE RECAP CLEANUP UTILITY ===")
    print("1. Delete generated outputs (outputs/ folder)")
    print("2. Delete source input videos (movies/ folder)")
    print("3. Clear temporary audio/video cache (temp/ folder)")
    print("0. Exit")
    choice = input("\nSelect an option [0-3]: ").strip()
    
    if choice == "1":
        out_dir = "outputs"
        if not os.path.exists(out_dir) or not os.listdir(out_dir):
            print("[INFO] No outputs found.")
            return
        PROTECTED_SYSTEM_FILES = {"api_usage_db.json", "movie_metadata.db"}
        items = sorted([f for f in os.listdir(out_dir) if f not in PROTECTED_SYSTEM_FILES])
        if not items:
            print("[INFO] No project outputs found to delete.")
            return
        for i, name in enumerate(items, 1):
            print(f"  {i}. {name}")
        sel = input("\nEnter number to delete (or 'all' for everything, 0 to cancel): ").strip().lower()
        if sel == "all":
            confirm = input("Are you sure you want to delete ALL outputs? (y/N): ").lower()
            if confirm == "y":
                def _safe_remove_path(path: str):
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    elif os.path.isfile(path):
                        try: os.remove(path)
                        except Exception: pass

                for name in items:
                    if name in PROTECTED_SYSTEM_FILES:
                        continue
                    _safe_remove_path(os.path.join("outputs", name))
                    _safe_remove_path(os.path.join("temp", name))
                print("[OK] All outputs and associated temp files deleted!")
        elif sel.isdigit() and 1 <= int(sel) <= len(items):
            name = items[int(sel)-1]
            def _safe_remove_path(path: str):
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.isfile(path):
                    try: os.remove(path)
                    except Exception: pass
            _safe_remove_path(os.path.join("outputs", name))
            _safe_remove_path(os.path.join("temp", name))
            print(f"[OK] Deleted output: {name}")
    elif choice == "2":
        mov_dir = "movies"
        if not os.path.exists(mov_dir) or not os.listdir(mov_dir):
            print("[INFO] No input videos found in movies/.")
            return
        items = sorted([f for f in os.listdir(mov_dir) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv'))])
        if not items:
            print("[INFO] No video files found in movies/.")
            return
        for i, name in enumerate(items, 1):
            print(f"  {i}. {name}")
        sel = input("\nEnter number to delete (or 'all' for everything, 0 to cancel): ").strip().lower()
        if sel == "all":
            confirm = input("Are you sure you want to delete ALL input movies? (y/N): ").lower()
            if confirm == "y":
                for name in items: os.remove(os.path.join("movies", name))
                print("[OK] All input movies deleted!")
        elif sel.isdigit() and 1 <= int(sel) <= len(items):
            name = items[int(sel)-1]
            os.remove(os.path.join("movies", name))
            print(f"[OK] Deleted input video: {name}")
    elif choice == "3":
        if os.path.exists("temp"):
            shutil.rmtree("temp", ignore_errors=True)
            os.makedirs("temp", exist_ok=True)
            print("[OK] Temporary cache cleared!")

def check_dependencies():
    ffmpeg = "/usr/local/bin/ffmpeg" if (os.path.exists("/usr/local/bin/ffmpeg") and os.path.getsize("/usr/local/bin/ffmpeg") > 10000000) else shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            ffmpeg = get_ffmpeg_exe()
        except ImportError:
            ffmpeg = None
    if not ffmpeg or not os.path.exists(ffmpeg):
        print("[CRITICAL ERROR] FFmpeg was not found. Install it or run: pip install imageio-ffmpeg")
        sys.exit(1)
    # MoviePy and the post-processing agent both honor this executable.
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg
    ffmpeg_dir = os.path.dirname(ffmpeg)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"[*] FFmpeg ready -> {ffmpeg}")

def main():
    check_dependencies()
    print(ASCII_ART)

    parser = argparse.ArgumentParser(
        description="Movie Recap AI — Free Local Pipeline",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "input_source",
        nargs="?",
        default=None,
        help="Path to video file or URL to download"
    )
    parser.add_argument(
        "-i", "--input",
        dest="input_flag",
        default=None,
        help="Path to video file or URL to download"
    )
    parser.add_argument(
        "-b", "--batch",
        action="store_true",
        help="Process all videos in movies/ folder sequentially"
    )
    parser.add_argument(
        "-u", "--urls",
        nargs="+",
        default=None,
        help="List of URLs to download and process in batch"
    )
    parser.add_argument(
        "-l", "--lang",
        dest="language",
        choices=["burmese", "english", "mm", "en", "burmese_nilar", "burmese_thiha", "nilar", "thiha"],
        default=None,
        help="Language for recap script and voiceover (default: burmese or config setting)"
    )
    parser.add_argument(
        "--blocks",
        type=int,
        default=None,
        help="Maximum number of narrative blocks (override config)"
    )
    parser.add_argument(
        "--subtitle",
        action="store_true",
        help="Enable subtitle blur pass in the final recap video"
    )

    parser.add_argument(
        "-v", "--voice",
        dest="tts_voice",
        default=None,
        help="TTS Voice: 'my-MM-NilarNeural' (Burmese Female), 'my-MM-ThihaNeural' (Burmese Male), 'nilar', 'thiha', etc."
    )
    parser.add_argument(
        "-e", "--engine",
        dest="engine",
        choices=["edge_tts", "f5_tts"],
        default=None,
        help="TTS Voiceover Engine: 'edge_tts' (free cloud) or 'f5_tts' (zero-shot cloning)"
    )
    parser.add_argument(
        "--engine-mode",
        dest="engine_mode",
        choices=["recap", "subtitle", "hardsub"],
        default="recap",
        help="Pipeline Engine: 'recap' (Movie Recap Video Studio), 'subtitle' (Subtitle Generator), or 'hardsub' (Original Audio & Burmese Hardsub Studio)"
    )
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="Mirror video horizontally for anti-copyright protection"
    )
    parser.add_argument(
        "--blur-height",
        type=float,
        default=None,
        help="Custom subtitle blur height ratio (e.g. 0.18, 0.25)"
    )
    parser.add_argument(
        "--audio-anti-copyright",
        action="store_true",
        help="Subtly perturb audio tempo (atempo=1.008) in Engine 3 to evade Content ID audio fingerprinting"
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Skip Text-to-Speech voice generation step"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process movies even if output already exists (ignore skip_completed)"
    )
    parser.add_argument(
        "--skip-demucs", "--no-demucs",
        action="store_true",
        help="Skip Demucs vocal separation (dramatically speeds up audio pipeline on CPU)"
    )
    parser.add_argument(
        "--detect-scenes",
        action="store_true",
        help="Enable PySceneDetect frame analysis (default: skipped for fast 1:1 dialogue dubbing)"
    )
    parser.add_argument(
        "--skip-scenes",
        action="store_true",
        help="Explicitly bypass PySceneDetect frame analysis"
    )
    parser.add_argument(
        "--thumb-title",
        dest="thumb_title",
        default=None,
        help="Custom Myanmar Title to burn on the Thumbnail (leave empty for auto AI title)"
    )
    parser.add_argument(
        "--watermark-text",
        dest="watermark_text",
        default=None,
        help="Custom watermark text to overlay on the video (default: Pai Ai Movie Studio)"
    )
    parser.add_argument(
        "--no-watermark",
        dest="no_watermark",
        action="store_true",
        help="Disable watermark overlay in the video"
    )
    parser.add_argument(
        "--format", "--aspect-ratio", "--video-size",
        dest="video_format",
        choices=["16:9", "9:16", "both"],
        default=None,
        help="Video output aspect ratio / format: '16:9' (YouTube landscape), '9:16' (Vertical Reels), or 'both' (Export both)"
    )
    parser.add_argument(
        "--reels",
        action="store_true",
        default=None,
        help="Force export of 9:16 Facebook Reels / TikTok Canvas video"
    )
    parser.add_argument(
        "--no-reels",
        action="store_true",
        help="Disable export of 9:16 Facebook Reels video"
    )
    parser.add_argument(
        "--sub-mode", "--subtitle-mode",
        dest="sub_mode",
        choices=["burn", "none", "auto"],
        default="burn",
        help="Subtitle mode: 'burn' (burn hardsub on video) or 'none' (voiceover only + separate SRT)"
    )
    parser.add_argument(
        "--sub-style", "--subtitle-style", "--preset",
        dest="subtitle_style",
        choices=["box_black", "yellow_pop", "white_stroke", "cyan_cyber", "crimson_box"],
        default=None,
        help="Subtitle style preset: 'box_black' (Cinema Box), 'yellow_pop' (TikTok Yellow), 'white_stroke' (Classic White), 'cyan_cyber' (Cyber Cyan), 'crimson_box' (Thriller Red Box)"
    )
    parser.add_argument(
        "--res", "--resolution",
        dest="resolution",
        choices=["1080p", "720p"],
        default="1080p",
        help="Video resolution preset: '1080p' (Full HD) or '720p' (Fast render HD)"
    )
    parser.add_argument(
        "--thumbnail-intro",
        action="store_true",
        default=None,
        help="Include 3-second thumbnail intro at the start of recap video"
    )
    parser.add_argument(
        "--no-thumbnail-intro",
        action="store_true",
        default=None,
        help="Disable 3-second thumbnail intro at start of video"
    )
    parser.add_argument(
        "--trim-end",
        type=float,
        default=None,
        help="Manual seconds to trim from the end of the video to discard original outro"
    )
    parser.add_argument(
        "--no-smart-trim",
        action="store_true",
        default=False,
        help="Disable automatic smart outro trimming at the end of video"
    )
    parser.add_argument(
        "--outro-card",
        action="store_true",
        default=None,
        help="Append 3-second 'Pai AI Movie Studio' branded Outro Card at video end"
    )
    parser.add_argument(
        "--no-outro-card",
        action="store_true",
        default=None,
        help="Disable 3-second outro card"
    )
    parser.add_argument(
        "--source-lang", "--source-language",
        dest="source_lang",
        choices=["auto", "zh", "en", "th", "ko", "ja"],
        default="auto",
        help="Source movie audio language for Whisper STT (default: auto, or 'zh', 'en', 'th', 'ko', 'ja')"
    )
    parser.add_argument(
        "--mode", "--script-engine",
        dest="script_engine",
        choices=["recap", "translate"],
        default="recap",
        help="Narration Script Engine: 'recap' (True Myanmar Movie Recap Storyteller) or 'translate' (1:1 Spoken Dialogue Dubbing)"
    )
    parser.add_argument(
        "--translation-style", "--style",
        dest="translation_style",
        choices=["recap", "dialogue", "persona"],
        default=None,
        help="Translation Style: 'recap' (Movie Recap Storyteller), 'dialogue' (1:1 Natural Spoken Subtitle), 'persona' (Gender & Kinship Persona Dubbing)"
    )
    parser.add_argument(
        "--audio-mode",
        dest="audio_mode",
        choices=["ai_voiceover", "original", "none"],
        default="ai_voiceover",
        help="Audio mode: 'ai_voiceover' (TTS narration), 'original' (100% original movie audio), 'none' (Mute original audio)"
    )
    parser.add_argument(
        "--sfx-mode",
        dest="sfx_mode",
        choices=["original_sfx", "bgm", "both", "none"],
        default="original_sfx",
        help="Background SFX audio: 'original_sfx' (Demucs foley), 'bgm' (Cinematic music), 'both' (Demucs + BGM mix), 'none' (Clean voiceover)"
    )
    parser.add_argument(
        "--sfx-volume",
        dest="sfx_volume",
        type=float,
        default=0.15,
        help="Background audio / SFX volume intensity (default: 0.15)"
    )
    parser.add_argument(
        "--blur-mode",
        dest="blur_mode",
        choices=["auto", "yes", "no"],
        default="auto",
        help="Vision AI Subtitle Blur: 'auto' (detect via Vision AI), 'yes' (force blur), 'no' (off)"
    )
    parser.add_argument(
        "--blur-height",
        dest="blur_height",
        type=float,
        default=None,
        help="Custom height percentage (0.05-0.35) for subtitle blur region"
    )
    parser.add_argument(
        "--mirror",
        dest="mirror",
        action="store_true",
        default=False,
        help="Mirror video horizontally for anti-copyright shield"
    )
    parser.add_argument(
        "--audio-anti-copyright",
        dest="audio_anti_copyright",
        action="store_true",
        default=False,
        help="Apply audio tempo shield (atempo=1.008) against Content ID matching"
    )
    parser.add_argument(
        "--no-render", "--subtitles-only",
        dest="no_render",
        action="store_true",
        default=False,
        help="Skip heavy video rendering and export subtitles and audio deliverables only"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume pipeline execution from the last completed phase checkpoint (default: True)"
    )
    parser.add_argument(
        "--fresh", "--force-restart",
        dest="fresh",
        action="store_true",
        default=False,
        help="Ignore existing checkpoints and restart the pipeline from Phase 1"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Interactive cleanup menu to delete old source videos or generated outputs"
    )

    args = parser.parse_args()
    setup_directories()

    if args.clean:
        run_interactive_cleanup()
        return

    chosen_format = args.video_format
    if args.no_reels:
        chosen_format = "16:9"
        os.environ["DISABLE_REELS"] = "true"
    elif args.reels:
        if not chosen_format:
            chosen_format = "both"
        os.environ["ENABLE_REELS"] = "true"

    if args.no_voice:
        os.environ["VOICE_ENABLED"] = "false"

    if args.blocks is not None:
        os.environ["MAX_BLOCKS"] = str(args.blocks)

    if args.subtitle:
        os.environ["ENABLE_SUBTITLES"] = "true"

    if args.skip_demucs:
        os.environ["SKIP_DEMUCS"] = "true"

    if args.detect_scenes:
        os.environ["SKIP_SCENES"] = "0"
    elif args.skip_scenes:
        os.environ["SKIP_SCENES"] = "1"

    # Multi-voice & language resolution
    clean_lang = args.language
    chosen_voice = args.tts_voice
    if clean_lang in ["burmese_nilar", "nilar"]:
        clean_lang = "burmese"
        if not chosen_voice:
            chosen_voice = "my-MM-NilarNeural"
    elif clean_lang in ["burmese_thiha", "thiha"]:
        clean_lang = "burmese"
        if not chosen_voice:
            chosen_voice = "my-MM-ThihaNeural"
    elif clean_lang in ["mm", "myanmar"]:
        clean_lang = "burmese"
    elif clean_lang in ["en"]:
        clean_lang = "english"
    elif chosen_voice in ["nilar", "female"]:
        chosen_voice = "my-MM-NilarNeural"
    elif chosen_voice in ["thiha", "male"]:
        chosen_voice = "my-MM-ThihaNeural"

    watermark_enabled = False if args.no_watermark else None
    thumb_intro = True if args.thumbnail_intro else (False if args.no_thumbnail_intro else None)
    outro_card_val = True if args.outro_card else (False if args.no_outro_card else None)
    should_resume = not args.fresh

    detect_scenes_flag = True if args.detect_scenes else (False if args.skip_scenes else None)

    # Single video or URL
    chosen_input = (args.input_flag or args.input_source or "").strip()
    if chosen_input:
        src = chosen_input

        if DownloaderAgent.is_url(src):
            print("[URL] Detected URL - starting auto-download...")
            try:
                downloader = DownloaderAgent(output_dir="movies")
                movie_path = downloader.download_video(src)
            except Exception as e:
                print(f"[ERROR] Download failed: {e}")
                sys.exit(1)
        else:
            movie_path = src
            if not os.path.exists(movie_path):
                print(f"[ERROR] File not found: '{movie_path}'")
                print("[TIP] If this is a URL, make sure it starts with http:// or https://")
                sys.exit(1)

        if args.engine_mode == "hardsub":
            from hardsub_engine import HardsubEngine
            engine = HardsubEngine()
            blur_opt = args.blur_mode if args.blur_mode else ("yes" if args.subtitle else "auto")
            engine.run(
                input_source=movie_path,
                video_format=chosen_format or "both",
                resolution=args.resolution or "1080p",
                subtitle_style=args.subtitle_style or "box_black",
                blur_mode=blur_opt,
                blur_height=args.blur_height,
                mirror=args.mirror,
                audio_anti_copyright=args.audio_anti_copyright,
                source_language=args.source_lang or "auto",
                translation_style=args.translation_style or "persona",
                audio_mode=args.audio_mode or "original",
                sfx_mode=args.sfx_mode or "original_sfx",
                sfx_volume=args.sfx_volume,
                render_video=not args.no_render,
            )
            return
        elif args.engine_mode == "subtitle":
            from subtitle_engine import SubtitleEngine
            engine = SubtitleEngine()
            engine.run(
                input_source=movie_path,
                source_language=args.source_lang or "auto",
                translation_style=args.translation_style or "dialogue",
                audio_mode=args.audio_mode or "original",
                sfx_mode=args.sfx_mode or "original_sfx",
                sfx_volume=args.sfx_volume,
                render_video=not args.no_render,
                video_format=chosen_format or "16:9",
                resolution=args.resolution or "1080p",
                subtitle_style=args.subtitle_style or "box_black",
                blur_mode=args.blur_mode or "auto",
                mirror=args.mirror,
                blur_height=args.blur_height,
                audio_anti_copyright=args.audio_anti_copyright,
            )
            return

        try:
            sub_mode = "burn" if args.subtitle else (args.sub_mode or "burn")
            master = MasterAgent(
                movie_path,
                language=clean_lang,
                subtitle_mode=sub_mode,
                subtitle_style=args.subtitle_style,
                resolution=args.resolution,
                tts_engine=args.engine,
                tts_voice=chosen_voice,
                custom_thumb_title=args.thumb_title,
                watermark_enabled=watermark_enabled,
                watermark_text=args.watermark_text,
                video_format=chosen_format,
                thumbnail_intro=thumb_intro,
                trim_end=args.trim_end,
                no_smart_trim=args.no_smart_trim,
                outro_card=outro_card_val,
                source_language=args.source_lang,
                script_engine=args.script_engine,
                resume=should_resume,
                skip_demucs=args.skip_demucs,
                detect_scenes=detect_scenes_flag,
                translation_style=args.translation_style,
                audio_mode=args.audio_mode,
                sfx_mode=args.sfx_mode,
                sfx_volume=args.sfx_volume,
                blur_mode=args.blur_mode,
                blur_height=args.blur_height,
                mirror=args.mirror,
                audio_anti_copyright=args.audio_anti_copyright,
                render_video=not args.no_render,
            )
            master.run_pipeline()
        except Exception as e:
            print(f"\n[ERROR] Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # Batch: movies/ folder
    elif args.batch:
        print("[BATCH] Processing all videos in movies/ folder...")
        conf = cfg.load_config()
        skip = conf.get("batch", {}).get("skip_completed", True) and not args.force
        sub_mode = "burn" if args.subtitle else (args.sub_mode or "burn")
        BatchProcessor(
            movies_folder=conf.get("batch", {}).get("movies_folder", "movies"),
            skip_completed=skip,
            language=clean_lang,
            subtitle_mode=sub_mode,
            subtitle_style=args.subtitle_style,
            resolution=args.resolution,
            tts_engine=args.engine,
            tts_voice=chosen_voice,
            custom_thumb_title=args.thumb_title,
            watermark_enabled=watermark_enabled,
            watermark_text=args.watermark_text,
            video_format=chosen_format,
            thumbnail_intro=thumb_intro,
            source_language=args.source_lang,
            script_engine=args.script_engine,
            resume=should_resume,
            skip_demucs=args.skip_demucs,
            detect_scenes=detect_scenes_flag,
        ).process_all()

    # Batch: URL list
    elif args.urls:
        print(f"[BATCH] URL Batch Mode: {len(args.urls)} video(s) to download & process...")
        conf = cfg.load_config()
        skip = conf.get("batch", {}).get("skip_completed", True) and not args.force
        sub_mode = "burn" if args.subtitle else (args.sub_mode or "burn")
        BatchProcessor(
            movies_folder=conf.get("batch", {}).get("movies_folder", "movies"),
            skip_completed=skip,
            language=clean_lang,
            subtitle_mode=sub_mode,
            subtitle_style=args.subtitle_style,
            resolution=args.resolution,
            tts_engine=args.engine,
            tts_voice=chosen_voice,
            custom_thumb_title=args.thumb_title,
            watermark_enabled=watermark_enabled,
            watermark_text=args.watermark_text,
            video_format=chosen_format,
            thumbnail_intro=thumb_intro,
            source_language=args.source_lang,
            script_engine=args.script_engine,
            resume=should_resume,
            skip_demucs=args.skip_demucs,
            detect_scenes=detect_scenes_flag,
        ).process_all(url_list=args.urls, local_paths=[])
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
