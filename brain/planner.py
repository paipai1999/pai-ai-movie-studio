import os
import glob
import json
from typing import List
from agents.master import MasterAgent
from agents.downloader_agent import DownloaderAgent
from brain.memory import MovieState  # Fix: was missing — caused NameError in _is_completed()
import brain.config as cfg

class BatchProcessor:
    def __init__(
        self,
        movies_folder: str = "movies",
        skip_completed: bool = True,
        language: str = None,
        subtitle_mode: str = "burn",
        resolution: str = "1080p",
        tts_engine: str = None,
        custom_thumb_title: str = None,
        watermark_enabled: bool = None,
        watermark_text: str = None,
        watermark_opacity: float = None,
        tts_voice: str = None,
        video_format: str = None,
        subtitle_style: str = None,
        thumbnail_intro: bool = None,
        source_language: str = "auto",
        script_engine: str = "recap",
        resume: bool = True,
        cancel_event=None,
        output_dir: str = None,
        skip_demucs: bool = None,
        detect_scenes: bool = None,
        translation_style: str = None,
        audio_mode: str = None,
        sfx_mode: str = None,
        sfx_volume: float = None,
        blur_mode: str = None,
        blur_height: float = None,
        mirror: bool = None,
        audio_anti_copyright: bool = None,
        render_video: bool = None,
        stage_toggles: dict = None,
    ):
        self.movies_folder = movies_folder
        self.output_dir = output_dir or cfg.load_config().get("paths", {}).get("output_dir", "outputs")
        self.skip_completed = skip_completed
        self.resume = bool(resume)
        self.cancel_event = cancel_event
        self.skip_demucs = skip_demucs
        self.detect_scenes = detect_scenes
        self.language = language
        self.source_language = source_language or "auto"
        self.script_engine = script_engine or "recap"
        self.subtitle_mode = subtitle_mode
        self.subtitle_style = subtitle_style
        self.resolution = resolution or "1080p"
        self.tts_engine = tts_engine
        self.tts_voice = tts_voice
        self.video_format = video_format
        self.custom_thumb_title = custom_thumb_title
        self.watermark_enabled = watermark_enabled
        self.watermark_text = watermark_text
        self.watermark_opacity = watermark_opacity
        self.thumbnail_intro = thumbnail_intro
        self.translation_style = translation_style
        self.audio_mode = audio_mode
        self.sfx_mode = sfx_mode
        self.sfx_volume = sfx_volume
        self.blur_mode = blur_mode
        self.blur_height = blur_height
        self.mirror = mirror
        self.audio_anti_copyright = audio_anti_copyright
        self.render_video = render_video
        self.stage_toggles = stage_toggles
        self.supported_extensions = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
        self.results = []

    def _is_completed(self, movie_path: str) -> bool:
        """Check if this movie already has a completed output state.json."""
        try:
            movie_name = os.path.splitext(os.path.basename(movie_path))[0]
            project_dir = MovieState(movie_name=movie_name).project_dir
            state_file = os.path.join(self.output_dir, project_dir, "state.json")
            if not os.path.exists(state_file):
                return False
            # Verify the state file is valid JSON and pipeline reached 100%
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("progress", 0)) >= 100 and data.get("pipeline_status") in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
        except Exception:
            return False  # If anything fails, re-process this movie

    def _collect_movies(self) -> List[str]:
        """Collect all supported video files from the movies folder."""
        movie_files = []
        for ext in self.supported_extensions:
            pattern = os.path.join(self.movies_folder, f"*{ext}")
            movie_files.extend(glob.glob(pattern))
        return sorted(movie_files)

    def process_all(self, url_list: List[str] = None, local_paths: List[str] = None):
        """
        Process all movies in the movies/ folder (batch mode).
        Optionally also download and process a list of URLs first.
        """
        # Step 1: Download from URLs if provided
        downloaded_paths = []
        if url_list:
            print(f"\n[URL] Batch Mode: Downloading {len(url_list)} video(s) from URLs...")
            downloader = DownloaderAgent(output_dir=self.movies_folder)
            for idx, url in enumerate(url_list, 1):
                if (self.cancel_event and getattr(self.cancel_event, "is_set", lambda: False)()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                    print(f"\n🛑 [STOP] Batch processing cancelled by user during download at item {idx}/{len(url_list)}.")
                    break
                print(f"\n[{idx}/{len(url_list)}] Downloading: {url}")
                try:
                    downloaded_path = downloader.download_video(url)
                    downloaded_paths.append(downloaded_path)
                    print(f"[OK] Downloaded: {downloaded_path}")
                except (InterruptedError, KeyboardInterrupt):
                    print(f"\n🛑 [STOP] Download cancelled: {url}")
                    self.results.append({"url": url, "status": "CANCELLED", "error": "Cancelled by user"})
                    break
                except Exception as e:
                    is_cancel = os.environ.get("CURRENT_JOB_CANCELLED") == "1" or (self.cancel_event and getattr(self.cancel_event, "is_set", lambda: False)())
                    status = "CANCELLED" if is_cancel else "DOWNLOAD_FAILED"
                    print(f"[ERROR] Download {status} for {url}: {e}")
                    self.results.append({"url": url, "status": status, "error": str(e)})
                    if is_cancel:
                        break

        # Step 2: Collect all local movies
        if local_paths is not None:
            movies = list(dict.fromkeys([*local_paths, *downloaded_paths]))
        else:
            movies = self._collect_movies()
        if not movies:
            print(f"[!] BatchProcessor: No video files found in '{self.movies_folder}/'")
            return

        total = len(movies)
        print(f"\n[VIDEO] Batch Mode: Found {total} video file(s) to process in '{self.movies_folder}/'")

        # Step 3: Process each movie sequentially
        for idx, movie_path in enumerate(movies, 1):
            if (self.cancel_event and getattr(self.cancel_event, "is_set", lambda: False)()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                print(f"\n🛑 [STOP] Batch processing cancelled by user at item {idx}/{total}.")
                break

            movie_name = os.path.splitext(os.path.basename(movie_path))[0]
            print(f"\n{'='*55}")
            print(f"[{idx}/{total}] Processing: {movie_name}")
            print(f"{'='*55}")

            # Skip already-completed jobs
            if self.skip_completed and self._is_completed(movie_path):
                print(f"[SKIP] Skipping '{movie_name}' - already completed (outputs/{movie_name}/state.json exists).")
                self.results.append({"movie": movie_name, "status": "SKIPPED"})
                continue

            try:
                master = MasterAgent(
                    movie_path,
                    language=self.language,
                    subtitle_mode=self.subtitle_mode,
                    resolution=self.resolution,
                    tts_engine=self.tts_engine,
                    tts_voice=self.tts_voice,
                    custom_thumb_title=self.custom_thumb_title,
                    watermark_enabled=self.watermark_enabled,
                    watermark_text=self.watermark_text,
                    watermark_opacity=self.watermark_opacity,
                    video_format=self.video_format,
                    subtitle_style=self.subtitle_style,
                    thumbnail_intro=self.thumbnail_intro,
                    source_language=self.source_language,
                    script_engine=self.script_engine,
                    resume=self.resume,
                    cancel_event=self.cancel_event,
                    skip_demucs=self.skip_demucs,
                    detect_scenes=self.detect_scenes,
                    translation_style=self.translation_style,
                    audio_mode=self.audio_mode,
                    sfx_mode=self.sfx_mode,
                    sfx_volume=self.sfx_volume,
                    blur_mode=self.blur_mode,
                    blur_height=self.blur_height,
                    mirror=self.mirror,
                    audio_anti_copyright=self.audio_anti_copyright,
                    render_video=self.render_video,
                    stage_toggles=self.stage_toggles,
                )
                master.run_pipeline()
                pipeline_status = getattr(master.state, "pipeline_status", "COMPLETED")
                result_status = "SUCCESS" if pipeline_status == "COMPLETED" else pipeline_status
                self.results.append({"movie": movie_name, "status": result_status, "warnings": getattr(master.state, "warnings", [])})
                print(f"[OK] [{idx}/{total}] Completed: {movie_name}")
            except (InterruptedError, KeyboardInterrupt):
                print(f"\n🛑 [STOP] [{idx}/{total}] CANCELLED by user: {movie_name}")
                self.results.append({"movie": movie_name, "status": "CANCELLED", "error": "Cancelled by user"})
                break
            except Exception as e:
                is_cancel = os.environ.get("CURRENT_JOB_CANCELLED") == "1" or (self.cancel_event and getattr(self.cancel_event, "is_set", lambda: False)())
                status = "CANCELLED" if is_cancel else "FAILED"
                print(f"[ERROR] [{idx}/{total}] {status}: {movie_name} - Error: {e}")
                self.results.append({"movie": movie_name, "status": status, "error": str(e)})
                if is_cancel:
                    break

        # Step 4: Print batch summary
        self._print_summary()

    def _print_summary(self):
        """Print a final summary report of the batch run."""
        success = [r for r in self.results if r.get("status") in {"SUCCESS", "COMPLETED"}]
        warnings = [r for r in self.results if r.get("status") == "COMPLETED_WITH_WARNINGS"]
        pending = [r for r in self.results if r.get("status") == "QA_PENDING"]
        cancelled = [r for r in self.results if r.get("status") == "CANCELLED"]
        failed  = [r for r in self.results if r.get("status") in {"FAILED", "DOWNLOAD_FAILED"}]
        skipped = [r for r in self.results if r.get("status") == "SKIPPED"]

        print(f"\n{'='*55}")
        print("[STATS] BATCH PROCESSING SUMMARY")
        print(f"{'='*55}")
        print(f"  [OK] Completed : {len(success)}")
        print(f"  [WARN] Warnings  : {len(warnings)}")
        print(f"  [QA] Pending    : {len(pending)}")
        print(f"  [SKIP] Skipped   : {len(skipped)}")
        print(f"  [STOP] Cancelled : {len(cancelled)}")
        print(f"  [ERROR] Failed    : {len(failed)}")
        if failed or cancelled:
            print("\n  Unfinished / Failed jobs:")
            for r in (*cancelled, *failed):
                name = r.get('movie') or r.get('url') or 'Unknown'
                print(f"    - [{r.get('status')}] {name}: {r.get('error','Unknown error')}")
        print(f"{'='*55}")

        # Save summary to JSON
        summary_path = os.path.join(self.output_dir, "batch_summary.json")
        os.makedirs(self.output_dir, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4)
        print(f"[SAVED] Batch summary saved -> {summary_path}")
