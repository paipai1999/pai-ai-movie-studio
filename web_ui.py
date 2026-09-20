import os
import sys
import re
import json
import uuid
import time
import threading
import io
import shutil
import posixpath
import asyncio
import traceback
import contextvars
import zipfile
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agents.downloader_agent import DownloaderAgent
from agents.master import MasterAgent
from agents.video_merger_agent import detect_hardware_encoder
from brain.sqlite_store import (
    delete_movie_state,
    list_movie_states,
    clean_stale_running_jobs,
    create_job,
    update_job,
)
from brain import config as cfg
from brain.config import SUBTITLE_PRESETS
from main import check_dependencies

# Setup FFmpeg path at startup
try:
    check_dependencies()
    _enc = detect_hardware_encoder()
    print(f"🚀 [WebUI Hardware Acceleration] Active Video Encoder: {_enc.get('label', 'Default')} [{_enc.get('codec', 'libx264')}]")
except Exception as e:
    print(f"[WARN] check_dependencies failed: {e}")

try:
    stale_count = clean_stale_running_jobs()
    if stale_count > 0:
        print(f"[*] WebUI: Reset {stale_count} stale running job(s) from previous session.")
except Exception as e:
    print(f"[WARN] clean_stale_running_jobs notice: {e}")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Movie Recap API", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _is_authenticated(request: Request) -> bool:
    auth_secret = os.getenv("WEB_UI_PASSWORD") or os.getenv("WEB_UI_TOKEN")
    if not auth_secret:
        return True

    # 1. Bearer token in Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token == auth_secret:
            return True

    # 2. Custom header
    if request.headers.get("x-auth-token", "").strip() == auth_secret:
        return True

    # 3. Query param (for testing or direct browser links)
    q_token = request.query_params.get("token") or request.query_params.get("auth") or request.query_params.get("password")
    if q_token and q_token.strip() == auth_secret:
        return True

    # 4. Cookie
    if request.cookies.get("web_ui_token", "").strip() == auth_secret:
        return True

    return False

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    auth_secret = os.getenv("WEB_UI_PASSWORD") or os.getenv("WEB_UI_TOKEN")
    if auth_secret:
        path = request.url.path
        exempt = path in ["/api/login", "/api/auth/status", "/favicon.ico"] or path.startswith("/static")
        if not exempt and not _is_authenticated(request):
            if path.startswith("/api/"):
                return JSONResponse(status_code=401, content={"status": "error", "detail": "Unauthorized: Password or Token required"})
            return HTMLResponse(
                content="""<!DOCTYPE html><html><head><title>Dashboard Login</title><meta name='viewport' content='width=device-width, initial-scale=1'>
<style>body{font-family:-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
.box{background:#161b22;padding:32px;border-radius:12px;border:1px solid #30363d;max-width:360px;width:90%;text-align:center;}
input{width:100%;box-sizing:border-box;padding:12px;margin:16px 0;background:#0d1117;border:1px solid #30363d;color:#fff;border-radius:6px;font-size:15px;}
button{width:100%;padding:12px;background:#238636;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:bold;font-size:15px;}
button:hover{background:#2ea043;}
</style></head><body><div class='box'><h2>🔒 Login Required</h2><p style='color:#8b949e;font-size:14px;'>This Movie Recap Web UI is password-protected.</p>
<form method='GET' action='/'><input type='password' name='token' placeholder='Enter Password / Token' required/><button type='submit'>Access Dashboard</button></form>
</div></body></html>""",
                status_code=401
            )

    response = await call_next(request)
    if auth_secret and _is_authenticated(request):
        q_token = request.query_params.get("token") or request.query_params.get("auth") or request.query_params.get("password")
        if q_token and q_token.strip() == auth_secret:
            response.set_cookie("web_ui_token", auth_secret, max_age=86400 * 7, httponly=True, samesite="lax")
    return response

templates = Jinja2Templates(directory="templates")

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.m4v')

jobs = {}
jobs_lock = threading.RLock()
cancel_events = {}
JOB_RETENTION_SECONDS = 7200  # Clean up finished jobs after 2 hours

# FIFO Job Queue
job_queue = []
queue_lock = threading.RLock()
_dispatcher_thread = None

def _queue_dispatcher():
    """Background worker that pulls jobs from FIFO queue sequentially."""
    while True:
        job_to_run = None
        with jobs_lock:
            running = any(j.get('status') == 'running' for j in jobs.values())
        if not running:
            with queue_lock:
                if job_queue:
                    job_to_run = job_queue.pop(0)
        if job_to_run:
            jid = job_to_run["job_id"]
            should_start = False
            with jobs_lock:
                if jid in jobs and jobs[jid].get("status") == "queued":
                    jobs[jid]["status"] = "running"
                    jobs[jid]["phase"] = "Starting..."
                    should_start = True
                    try:
                        update_job(jid, status="running", phase="Starting...")
                    except Exception:
                        pass
                else:
                    print(f"[*] Queue Dispatcher: Skipping job {jid} (status: {jobs.get(jid, {}).get('status')})")
            if should_start:
                print(f"[*] Queue Dispatcher: Starting next queued job: {jid} ({job_to_run.get('name', 'video')})")
                t = threading.Thread(
                    target=job_to_run["target"],
                    args=job_to_run["args"],
                    daemon=True
                )
                t.start()
        time.sleep(1.0)

def _ensure_queue_dispatcher():
    global _dispatcher_thread
    with queue_lock:
        if _dispatcher_thread is None or not _dispatcher_thread.is_alive():
            _dispatcher_thread = threading.Thread(target=_queue_dispatcher, daemon=True)
            _dispatcher_thread.start()

# Launch queue dispatcher on module load
_ensure_queue_dispatcher()

def _cleanup_old_jobs():
    """Remove completed/error jobs older than JOB_RETENTION_SECONDS to prevent memory growth."""
    now = time.time()
    with jobs_lock:
        to_delete = [
            jid for jid, job in list(jobs.items())
            if job.get('status') in ('done', 'error', 'cancelled')
            and now - job.get('created_at', now) > JOB_RETENTION_SECONDS
        ]
        for jid in to_delete:
            jobs.pop(jid, None)
            # BUG-C6 Fix: Also free thread_stdout buffers and subscribers to prevent memory leak
            t_out = globals().get('thread_stdout')
            if t_out and hasattr(t_out, 'buffers'):
                t_out.buffers.pop(jid, None)
            if t_out and hasattr(t_out, 'subscribers'):
                t_out.subscribers.pop(jid, None)

def _has_running_job():
    with jobs_lock:
        return any(job.get('status') == 'running' for job in jobs.values())

def _resolve_input_source(input_source: str) -> str:
    """Resolve a dashboard filename to movies/ while still allowing valid local paths."""
    source = str(input_source or '').strip()
    if not source:
        raise ValueError("No input provided")
    if DownloaderAgent.is_url(source):
        return source
    if os.path.exists(source):
        return os.path.abspath(source)
    if not os.path.dirname(source):
        movies_path = os.path.join('movies', source)
        if os.path.exists(movies_path):
            return os.path.abspath(movies_path)
    raise FileNotFoundError(f"File not found: '{source}'")

def _safe_child_path(folder_type: str, item_name: str):
    if folder_type not in {'outputs', 'movies', 'temp'} or not item_name:
        return None
    base = os.path.abspath(folder_type)
    candidate = os.path.abspath(os.path.join(base, item_name))
    try:
        return candidate if os.path.commonpath([base, candidate]) == base else None
    except ValueError:
        return None


# Use contextvars to propagate Job ID across thread pools automatically (Python 3.7+)
current_job_id = contextvars.ContextVar("current_job_id", default=None)

class ThreadedStdout:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.buffers = {}
        self.subscribers = {}

    def write(self, s):
        jid = current_job_id.get()
        if not jid and self.buffers:
            # Fallback: associate with active job buffer if current_job_id wasn't inherited
            if len(self.buffers) == 1:
                jid = next(iter(self.buffers.keys()))
            else:
                jid = list(self.buffers.keys())[-1]

        if jid and jid in self.buffers:
            try:
                self.buffers[jid].write(s)
            except Exception:
                pass
            if jid in self.subscribers:
                for item in list(self.subscribers.get(jid, [])):
                    try:
                        if isinstance(item, tuple):
                            q, loop = item
                            if loop.is_running():
                                loop.call_soon_threadsafe(q.put_nowait, s)
                        else:
                            item.put_nowait(s)
                    except Exception:
                        pass
        try:
            self.original_stdout.write(s)
            self.original_stdout.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self.original_stdout, "isatty", lambda: False)()

    def fileno(self):
        if hasattr(self.original_stdout, "fileno"):
            return self.original_stdout.fileno()
        raise io.UnsupportedOperation("fileno")

    def reconfigure(self, **kwargs):
        if hasattr(self.original_stdout, "reconfigure"):
            self.original_stdout.reconfigure(**kwargs)

    def __getattr__(self, name):
        return getattr(self.original_stdout, name)

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

thread_stdout = ThreadedStdout(sys.stdout)
sys.stdout = thread_stdout
sys.stderr = thread_stdout

def pipeline_worker(
    job_id,
    input_source,
    language="burmese",
    subtitle_mode="burn",
    resolution="1080p",
    tts_engine=None,
    custom_thumb_title=None,
    watermark_enabled=None,
    watermark_text=None,
    watermark_opacity=None,
    reels_enabled=True,
    video_format="both",
    subtitle_style="box_black",
    thumbnail_intro=False,
    source_language="auto",
    skip_demucs=False,
    detect_scenes=False,
    resume=True,
    tts_voice=None,
    script_engine="recap",
    trim_end=None,
    no_smart_trim=False,
    outro_card=False,
):
    current_job_id.set(job_id)
    cancel_events[job_id] = threading.Event()
    os.environ["CURRENT_JOB_CANCELLED"] = "0"
    if skip_demucs:
        os.environ["SKIP_DEMUCS"] = "true"
    else:
        os.environ.pop("SKIP_DEMUCS", None)

    if detect_scenes:
        os.environ["SKIP_SCENES"] = "0"
    else:
        os.environ["SKIP_SCENES"] = "1"

    if video_format == "16:9" or reels_enabled is False:
        os.environ["DISABLE_REELS"] = "true"
        os.environ.pop("ENABLE_REELS", None)
    elif video_format in ["9:16", "both"] or reels_enabled is True:
        os.environ["ENABLE_REELS"] = "true"
        os.environ.pop("DISABLE_REELS", None)

    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer
    
    try:
        create_job(job_id, str(input_source), phase="Starting...")
    except Exception:
        pass
    
    try:
        if DownloaderAgent.is_url(input_source):
            with jobs_lock:
                jobs[job_id]['phase'] = 'Downloading Video...'
            try:
                update_job(job_id, phase='Downloading Video...')
            except Exception:
                pass
            print(f"[URL] Detected URL: {input_source} - starting auto-download...")
            downloader = DownloaderAgent(output_dir="movies")
            movie_path = downloader.download_video(input_source)
        else:
            with jobs_lock:
                jobs[job_id]['phase'] = 'Processing Local File...'
            movie_path = _resolve_input_source(input_source)
        
        # Multi-Voice Mapping
        tts_voice_override = tts_voice
        clean_lang = language
        if tts_voice_override:
            if tts_voice_override in ["thiha", "male", "burmese_thiha"]:
                tts_voice_override = "my-MM-ThihaNeural"
            elif tts_voice_override in ["nilar", "female", "burmese_nilar"]:
                tts_voice_override = "my-MM-NilarNeural"
            elif tts_voice_override in ["guy", "english_guy"]:
                tts_voice_override = "en-US-GuyNeural"
            elif tts_voice_override in ["jenny", "english_jenny"]:
                tts_voice_override = "en-US-JennyNeural"
        elif language in ["burmese_thiha", "thiha"]:
            clean_lang = "burmese"
            tts_voice_override = "my-MM-ThihaNeural"
        elif language in ["burmese_nilar", "nilar"]:
            clean_lang = "burmese"
            tts_voice_override = "my-MM-NilarNeural"
        elif language in ["burmese", "mm", "myanmar"]:
            clean_lang = "burmese"
            tts_voice_override = "my-MM-ThihaNeural"  # Auto multi-voice enabled
        elif language in ["english_guy", "guy"]:
            clean_lang = "english"
            tts_voice_override = "en-US-GuyNeural"
        elif language in ["english_jenny", "jenny"]:
            clean_lang = "english"
            tts_voice_override = "en-US-JennyNeural"
        elif language in ["english", "en"]:
            clean_lang = "english"
            tts_voice_override = "en-US-GuyNeural"    # Auto multi-voice enabled

        master = MasterAgent(
            movie_path,
            language=clean_lang,
            subtitle_mode=subtitle_mode,
            subtitle_style=subtitle_style,
            resolution=resolution,
            tts_engine=tts_engine,
            tts_voice=tts_voice_override,
            custom_thumb_title=custom_thumb_title,
            watermark_enabled=watermark_enabled,
            watermark_text=watermark_text,
            watermark_opacity=watermark_opacity,
            video_format=video_format,
            thumbnail_intro=thumbnail_intro,
            source_language=source_language,
            script_engine=script_engine,
            resume=resume,
            trim_end=trim_end,
            no_smart_trim=no_smart_trim,
            outro_card=outro_card,
            cancel_event=cancel_events.get(job_id),
            skip_demucs=skip_demucs,
            detect_scenes=detect_scenes,
        )
        master.run_pipeline()
        
        job_cancel_ev = cancel_events.get(job_id)
        if (job_cancel_ev and job_cancel_ev.is_set()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            with jobs_lock:
                jobs[job_id]['status'] = 'done'
            try:
                update_job(job_id, status='done', phase='Done')
            except Exception:
                pass
    except Exception as e:
        job_cancel_ev = cancel_events.get(job_id)
        is_cancel = isinstance(e, (InterruptedError, KeyboardInterrupt)) or (job_cancel_ev and job_cancel_ev.is_set()) or (os.environ.get("CURRENT_JOB_CANCELLED") == "1")
        if is_cancel:
            print(f"\n🛑 [STOP] Job {job_id} was force-stopped by user.")
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            traceback.print_exc()
            err_msg = str(e) or type(e).__name__
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = err_msg
                jobs[job_id]['phase'] = f"Error: {err_msg[:60]}"
            try:
                update_job(job_id, status='error', phase=f"Error: {err_msg[:60]}")
            except Exception:
                pass
    finally:
        # Free log buffer immediately on job end
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

def subtitle_worker(
    job_id,
    input_source,
    project_name=None,
    source_language="auto",
    force_whisper=False,
):
    current_job_id.set(job_id)
    cancel_events[job_id] = threading.Event()
    os.environ["CURRENT_JOB_CANCELLED"] = "0"
    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer

    try:
        create_job(job_id, str(input_source), phase="Starting Subtitle Engine...")
    except Exception:
        pass

    try:
        from subtitle_engine import SubtitleEngine
        engine = SubtitleEngine(output_base_dir="outputs", cancel_event=cancel_events.get(job_id))
        with jobs_lock:
            jobs[job_id]['phase'] = 'Processing Subtitles...'
        print(f"[*] Subtitle Engine: Starting job {job_id} for {input_source}...")
        engine.run(
            input_source=input_source,
            project_name=project_name,
            source_language=source_language,
            force_whisper=force_whisper
        )

        job_cancel_ev = cancel_events.get(job_id)
        if (job_cancel_ev and job_cancel_ev.is_set()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            with jobs_lock:
                jobs[job_id]['status'] = 'done'
                jobs[job_id]['phase'] = 'Done'
            try:
                update_job(job_id, status='done', phase='Done')
            except Exception:
                pass
    except Exception as e:
        job_cancel_ev = cancel_events.get(job_id)
        is_cancel = isinstance(e, (InterruptedError, KeyboardInterrupt)) or (job_cancel_ev and job_cancel_ev.is_set()) or (os.environ.get("CURRENT_JOB_CANCELLED") == "1")
        if is_cancel:
            print(f"\n🛑 [STOP] Job {job_id} was force-stopped by user.")
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            traceback.print_exc()
            err_msg = str(e) or type(e).__name__
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = err_msg
                jobs[job_id]['phase'] = f"Error: {err_msg[:60]}"
            try:
                update_job(job_id, status='error', phase=f"Error: {err_msg[:60]}")
            except Exception:
                pass
    finally:
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

def hardsub_worker(
    job_id,
    input_source,
    project_name=None,
    source_language="auto",
    force_whisper=False,
    video_format="both",
    resolution="1080p",
    subtitle_style="box_black",
    blur_mode="auto",
    mirror=False,
    color_grading=True,
    blur_height=None,
    audio_anti_copyright=False,
):
    current_job_id.set(job_id)
    cancel_events[job_id] = threading.Event()
    os.environ["CURRENT_JOB_CANCELLED"] = "0"
    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer

    try:
        create_job(job_id, str(input_source), phase="Starting Hardsub Studio...")
    except Exception:
        pass

    try:
        from hardsub_engine import HardsubEngine
        engine = HardsubEngine(output_base_dir="outputs", cancel_event=cancel_events[job_id])
        with jobs_lock:
            jobs[job_id]['phase'] = 'Processing Hardsub Video...'
        print(f"[*] Hardsub Studio: Starting job {job_id} for {input_source} (Format: {video_format}, Res: {resolution})...")
        engine.run(
            input_source=input_source,
            project_name=project_name,
            source_language=source_language,
            force_whisper=force_whisper,
            video_format=video_format,
            resolution=resolution,
            subtitle_style=subtitle_style,
            blur_mode=blur_mode,
            blur_height=blur_height,
            mirror=mirror,
            color_grading=color_grading,
            audio_anti_copyright=audio_anti_copyright,
        )

        job_cancel_ev = cancel_events.get(job_id)
        if (job_cancel_ev and job_cancel_ev.is_set()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            with jobs_lock:
                jobs[job_id]['status'] = 'done'
                jobs[job_id]['phase'] = 'Done'
            try:
                update_job(job_id, status='done', phase='Done')
            except Exception:
                pass
    except Exception as e:
        job_cancel_ev = cancel_events.get(job_id)
        is_cancel = isinstance(e, (InterruptedError, KeyboardInterrupt)) or (job_cancel_ev and job_cancel_ev.is_set()) or (os.environ.get("CURRENT_JOB_CANCELLED") == "1")
        if is_cancel:
            print(f"\n🛑 [STOP] Hardsub job {job_id} was force-stopped by user.")
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            traceback.print_exc()
            err_msg = str(e) or type(e).__name__
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = err_msg
                jobs[job_id]['phase'] = f"Error: {err_msg[:60]}"
            try:
                update_job(job_id, status='error', phase=f"Error: {err_msg[:60]}")
            except Exception:
                pass
    finally:
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

def batch_worker(
    job_id,
    inputs_list,
    language="burmese",
    subtitle_mode="burn",
    resolution="1080p",
    tts_engine=None,
    custom_thumb_title=None,
    watermark_enabled=None,
    watermark_text=None,
    watermark_opacity=None,
    reels_enabled=True,
    video_format="both",
    subtitle_style="box_black",
    thumbnail_intro=False,
    source_language="auto",
    skip_demucs=False,
    detect_scenes=False,
    resume=True,
    tts_voice=None,
    script_engine="recap",
    engine_mode="recap",
    blur_mode="auto",
    blur_height=None,
    mirror=False,
    color_grading=True,
    audio_anti_copyright=False,
    force_whisper=False,
):
    from brain.planner import BatchProcessor
    current_job_id.set(job_id)
    cancel_events[job_id] = threading.Event()
    os.environ["CURRENT_JOB_CANCELLED"] = "0"
    if skip_demucs:
        os.environ["SKIP_DEMUCS"] = "true"
    else:
        os.environ.pop("SKIP_DEMUCS", None)

    if detect_scenes:
        os.environ["SKIP_SCENES"] = "0"
    else:
        os.environ["SKIP_SCENES"] = "1"

    if video_format == "16:9" or reels_enabled is False:
        os.environ["DISABLE_REELS"] = "true"
        os.environ.pop("ENABLE_REELS", None)
    elif video_format in ["9:16", "both"] or reels_enabled is True:
        os.environ["ENABLE_REELS"] = "true"
        os.environ.pop("DISABLE_REELS", None)

    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer
    
    try:
        create_job(job_id, f"Batch ({len(inputs_list)} items)", phase="Starting...")
    except Exception:
        pass
    
    try:
        total_items = len(inputs_list)
        if engine_mode == "hardsub":
            from hardsub_engine import HardsubEngine
            print(f"[*] Batch Hardsub Studio: Starting batch of {total_items} items...")
            hardsub_eng = HardsubEngine(output_base_dir="outputs", cancel_event=cancel_events.get(job_id))
            for idx, item in enumerate(inputs_list, 1):
                if (cancel_events.get(job_id) and cancel_events[job_id].is_set()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                    break
                with jobs_lock:
                    jobs[job_id]['phase'] = f"Hardsub Item {idx}/{total_items}: {os.path.basename(item)[:30]}..."
                print(f"\n{'='*65}\n[BATCH HARDSUB] Item {idx}/{total_items}: {item}\n{'='*65}")
                try:
                    hardsub_eng.run(
                        input_source=item,
                        source_language=source_language or "auto",
                        force_whisper=force_whisper,
                        video_format=video_format or "both",
                        resolution=resolution or "1080p",
                        subtitle_style=subtitle_style or "box_black",
                        blur_mode=blur_mode or "auto",
                        blur_height=blur_height,
                        mirror=mirror,
                        color_grading=color_grading,
                        audio_anti_copyright=audio_anti_copyright,
                    )
                except Exception as item_err:
                    print(f"[ERROR] Batch item {idx} failed: {item_err}")
        elif engine_mode == "subtitle":
            from subtitle_engine import SubtitleEngine
            print(f"[*] Batch Subtitle Engine: Starting batch of {total_items} items...")
            sub_eng = SubtitleEngine(output_base_dir="outputs", cancel_event=cancel_events.get(job_id))
            for idx, item in enumerate(inputs_list, 1):
                if (cancel_events.get(job_id) and cancel_events[job_id].is_set()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                    break
                with jobs_lock:
                    jobs[job_id]['phase'] = f"Subtitle Item {idx}/{total_items}: {os.path.basename(item)[:30]}..."
                print(f"\n{'='*65}\n[BATCH SUBTITLE] Item {idx}/{total_items}: {item}\n{'='*65}")
                try:
                    sub_eng.run(
                        input_source=item,
                        source_language=source_language or "auto",
                        force_whisper=force_whisper,
                    )
                except Exception as item_err:
                    print(f"[ERROR] Batch item {idx} failed: {item_err}")
        else:
            urls = [i for i in inputs_list if DownloaderAgent.is_url(i)]
            local_paths = [_resolve_input_source(i) for i in inputs_list if not DownloaderAgent.is_url(i)]
            # Multi-Voice Mapping
            tts_voice_override = tts_voice
            clean_lang = language
            if tts_voice_override:
                if tts_voice_override in ["thiha", "male", "burmese_thiha"]:
                    tts_voice_override = "my-MM-ThihaNeural"
                elif tts_voice_override in ["nilar", "female", "burmese_nilar"]:
                    tts_voice_override = "my-MM-NilarNeural"
                elif tts_voice_override in ["guy", "english_guy"]:
                    tts_voice_override = "en-US-GuyNeural"
                elif tts_voice_override in ["jenny", "english_jenny"]:
                    tts_voice_override = "en-US-JennyNeural"
            elif language in ["burmese_thiha", "thiha"]:
                clean_lang = "burmese"
                tts_voice_override = "my-MM-ThihaNeural"
            elif language in ["burmese_nilar", "nilar"]:
                clean_lang = "burmese"
                tts_voice_override = "my-MM-NilarNeural"
            elif language in ["burmese", "mm", "myanmar"]:
                clean_lang = "burmese"
                tts_voice_override = "my-MM-ThihaNeural"
            elif language in ["english_guy", "guy"]:
                clean_lang = "english"
                tts_voice_override = "en-US-GuyNeural"
            elif language in ["english_jenny", "jenny"]:
                clean_lang = "english"
                tts_voice_override = "en-US-JennyNeural"
            elif language in ["english", "en"]:
                clean_lang = "english"
                tts_voice_override = "en-US-GuyNeural"

            processor = BatchProcessor(
                movies_folder="movies",
                skip_completed=True,
                language=clean_lang,
                subtitle_mode=subtitle_mode,
                subtitle_style=subtitle_style,
                resolution=resolution,
                tts_engine=tts_engine,
                tts_voice=tts_voice_override,
                custom_thumb_title=custom_thumb_title,
                watermark_enabled=watermark_enabled,
                watermark_text=watermark_text,
                watermark_opacity=watermark_opacity,
                video_format=video_format,
                thumbnail_intro=thumbnail_intro,
                source_language=source_language,
                script_engine=script_engine,
                resume=resume,
                cancel_event=cancel_events.get(job_id),
                skip_demucs=skip_demucs,
                detect_scenes=detect_scenes,
            )
            print(f"[*] Batch Mode: Starting batch run for {len(inputs_list)} item(s)...")
            processor.process_all(url_list=urls, local_paths=local_paths)
        
        job_cancel_ev = cancel_events.get(job_id)
        if (job_cancel_ev and job_cancel_ev.is_set()) or os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            with jobs_lock:
                jobs[job_id]['status'] = 'done'
            try:
                update_job(job_id, status='done', phase='Done')
            except Exception:
                pass
    except Exception as e:
        job_cancel_ev = cancel_events.get(job_id)
        is_cancel = isinstance(e, (InterruptedError, KeyboardInterrupt)) or (job_cancel_ev and job_cancel_ev.is_set()) or (os.environ.get("CURRENT_JOB_CANCELLED") == "1")
        if is_cancel:
            print(f"\n🛑 [STOP] Batch job {job_id} was force-stopped by user.")
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            traceback.print_exc()
            err_msg = str(e) or type(e).__name__
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = err_msg
                jobs[job_id]['phase'] = f"Error: {err_msg[:60]}"
            try:
                update_job(job_id, status='error', phase=f"Error: {err_msg[:60]}")
            except Exception:
                pass
    finally:
        # Free log buffer immediately on batch job end
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

# ── Pydantic Request Models ──
class StartRequest(BaseModel):
    input: str
    engine_mode: Optional[str] = "recap"
    project_name: Optional[str] = None
    force_whisper: Optional[bool] = False
    language: Optional[str] = "burmese"
    subtitle_mode: Optional[str] = "burn"
    resolution: Optional[str] = "1080p"
    tts_engine: Optional[str] = None
    tts_voice: Optional[str] = None
    custom_thumb_title: Optional[str] = None
    watermark_enabled: Optional[bool] = True
    watermark_text: Optional[str] = None
    watermark_opacity: Optional[float] = None
    reels_enabled: Optional[bool] = True
    video_format: Optional[str] = "both"
    subtitle_style: Optional[str] = "box_black"
    thumbnail_intro: Optional[bool] = False
    source_language: Optional[str] = "auto"
    skip_demucs: Optional[bool] = False
    detect_scenes: Optional[bool] = False
    script_engine: Optional[str] = "recap"
    resume: Optional[bool] = True
    trim_end: Optional[float] = None
    no_smart_trim: Optional[bool] = False
    outro_card: Optional[bool] = False
    blur_mode: Optional[str] = "auto"
    blur_height: Optional[float] = None
    mirror: Optional[bool] = False
    color_grading: Optional[bool] = True
    audio_anti_copyright: Optional[bool] = False

class BatchStartRequest(BaseModel):
    inputs: List[str]
    engine_mode: Optional[str] = "recap"
    force_whisper: Optional[bool] = False
    language: Optional[str] = "burmese"
    subtitle_mode: Optional[str] = "burn"
    resolution: Optional[str] = "1080p"
    tts_engine: Optional[str] = None
    tts_voice: Optional[str] = None
    custom_thumb_title: Optional[str] = None
    watermark_enabled: Optional[bool] = True
    watermark_text: Optional[str] = None
    watermark_opacity: Optional[float] = None
    reels_enabled: Optional[bool] = True
    video_format: Optional[str] = "both"
    subtitle_style: Optional[str] = "box_black"
    thumbnail_intro: Optional[bool] = False
    source_language: Optional[str] = "auto"
    skip_demucs: Optional[bool] = False
    detect_scenes: Optional[bool] = False
    script_engine: Optional[str] = "recap"
    resume: Optional[bool] = True
    blur_mode: Optional[str] = "auto"
    blur_height: Optional[float] = None
    mirror: Optional[bool] = False
    color_grading: Optional[bool] = True
    audio_anti_copyright: Optional[bool] = False

class SubtitleConfigRequest(BaseModel):
    preset: str = "box_black"

class BrandingConfigRequest(BaseModel):
    watermark_enabled: bool = True
    watermark_text: str = "Pai Ai Movie Studio"
    watermark_opacity: float = 0.4
    watermark_margin: int = 30
    watermark_font_size: int = 40

class RenameRequest(BaseModel):
    old_name: str
    new_name: str

class SaveKeysRequest(BaseModel):
    keys: List[str]

class CookieSaveRequest(BaseModel):
    content: str

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/system/info")
def system_info():
    enc = detect_hardware_encoder()
    with jobs_lock:
        active = _has_running_job()
    return {
        "hardware_encoder": enc,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "active_jobs": active
    }

@app.get("/api/system/health-check")
async def system_health_check():
    """Performs a comprehensive diagnostic on FFmpeg, GPU Encoder, Gemini Keys, Edge-TTS, and Disk."""
    import urllib.request, shutil

    results = {
        "status": "ok",
        "timestamp": time.time(),
        "checks": {}
    }

    # 1. FFmpeg & Hardware Encoder
    try:
        from agents.video_merger_agent import detect_hardware_encoder, _get_ffmpeg_bin
        ff_bin = _get_ffmpeg_bin()
        enc = detect_hardware_encoder()
        results["checks"]["ffmpeg"] = {
            "status": "ok",
            "installed": bool(ff_bin),
            "binary": os.path.basename(ff_bin) if ff_bin else "not_found",
            "encoder": enc.get("label", "CPU"),
            "codec": enc.get("codec", "libx264"),
            "type": enc.get("type", "cpu"),
            "is_gpu": enc.get("type") == "gpu",
            "details": f"{enc.get('label', 'CPU')} ({enc.get('codec', 'libx264')})"
        }
    except Exception as e:
        results["checks"]["ffmpeg"] = {"status": "error", "installed": False, "healthy": False, "error": str(e), "details": str(e)}
        results["status"] = "warning"

    # 2. Gemini API Keys Health
    try:
        c = cfg.load_config()
        keys = c.get("gemini", {}).get("api_keys", []) or []
        env_k = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")
        if env_k:
            for ek in env_k.replace(";", ",").split(","):
                if ek.strip() and ek.strip() not in keys:
                    keys.append(ek.strip())

        key_reports = []
        valid_keys = 0
        for k in keys:
            k = str(k).strip()
            if not k:
                continue
            masked = (k[:6] + "..." + k[-4:]) if len(k) > 10 else "***"
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={k}"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    if resp.status == 200:
                        key_reports.append({"key": masked, "key_preview": masked, "status": "active", "code": 200})
                        valid_keys += 1
                    else:
                        key_reports.append({"key": masked, "key_preview": masked, "status": "unexpected", "code": resp.status})
            except urllib.error.HTTPError as he:
                if he.code == 429:
                    key_reports.append({"key": masked, "key_preview": masked, "status": "rate_limited", "code": 429})
                elif he.code in (400, 403):
                    key_reports.append({"key": masked, "key_preview": masked, "status": "invalid_key", "code": he.code})
                else:
                    key_reports.append({"key": masked, "key_preview": masked, "status": f"http_{he.code}", "code": he.code})
            except Exception as ex:
                key_reports.append({"key": masked, "key_preview": masked, "status": "connection_error", "error": str(ex)[:60], "code": 0})

        gemini_healthy = valid_keys > 0
        gemini_status = "ok" if gemini_healthy else ("rate_limited" if any(r.get("status") == "rate_limited" for r in key_reports) else "warning")
        results["checks"]["gemini"] = {
            "status": gemini_status,
            "healthy": gemini_healthy,
            "total_keys": len(key_reports),
            "valid_keys": valid_keys,
            "results": key_reports,
            "details": key_reports
        }
        if not gemini_healthy:
            results["status"] = "warning"
    except Exception as e:
        results["checks"]["gemini"] = {"status": "error", "healthy": False, "error": str(e), "total_keys": 0, "valid_keys": 0}
        results["status"] = "warning"

    # 3. Edge-TTS Connectivity
    try:
        import edge_tts
        import asyncio
        t0 = time.time()
        async def _check_tts():
            voices = await edge_tts.list_voices()
            return any(v.get("ShortName") == "my-MM-ThihaNeural" for v in voices)
        has_voice = await asyncio.wait_for(_check_tts(), timeout=7.0)
        elapsed = round((time.time() - t0) * 1000, 1)
        results["checks"]["edge_tts"] = {
            "status": "ok",
            "healthy": True,
            "myanmar_voice_available": has_voice,
            "latency_ms": elapsed,
            "details": f"Online (Latency: {elapsed}ms, Myanmar voice ready: {has_voice})"
        }
    except Exception as e:
        results["checks"]["edge_tts"] = {"status": "error", "healthy": False, "error": str(e)[:80], "details": str(e)[:80]}
        results["status"] = "warning"

    # 4. Disk Space Check
    try:
        du = shutil.disk_usage(".")
        free_gb = round(du.free / (1024 ** 3), 2)
        total_gb = round(du.total / (1024 ** 3), 2)
        disk_healthy = free_gb >= 5.0
        results["checks"]["disk"] = {
            "status": "ok" if disk_healthy else "low_disk",
            "healthy": disk_healthy,
            "free_gb": free_gb,
            "total_gb": total_gb,
            "percent_free": round((du.free / du.total) * 100, 1),
            "details": f"{free_gb} GB free of {total_gb} GB ({round((du.free / du.total) * 100, 1)}% available)"
        }
        if not disk_healthy:
            results["status"] = "warning"
    except Exception as e:
        results["checks"]["disk"] = {"status": "error", "healthy": False, "error": str(e), "details": str(e)}

    return results

@app.get("/api/jobs/active")
def get_active_job():
    with jobs_lock:
        for jid, jdata in list(jobs.items()):
            if jdata.get("status") == "running":
                return {
                    "job_id": jid,
                    "name": jdata.get("name", "video"),
                    "source": jdata.get("source") or jdata.get("name", "video"),
                    "language": jdata.get("language", "burmese"),
                    "tts_engine": jdata.get("tts_engine", "edge_tts"),
                    "status": "running",
                    "phase": jdata.get("phase", "Running..."),
                    "created_at": jdata.get("created_at")
                }
    return {"job_id": None, "status": "idle"}

def _get_cookie_paths():
    return [
        "cookies.txt",
        os.path.join("assets", "cookies.txt"),
        "/kaggle/working/cookies.txt",
        "/kaggle/working/ai-translate-agent/cookies.txt",
        "/content/cookies.txt",
        "/content/drive/MyDrive/MovieRecapOutputs/cookies.txt"
    ]

def _save_cookie_content(content_bytes: bytes):
    saved_paths = []
    # 1. Local and assets/
    for p in ["cookies.txt", os.path.join("assets", "cookies.txt")]:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            with open(p, "wb") as f:
                f.write(content_bytes)
            saved_paths.append(p)
        except Exception:
            pass
    # 2. Google Drive for Colab
    drive_out = "/content/drive/MyDrive/MovieRecapOutputs"
    if os.path.exists(drive_out):
        try:
            dp = os.path.join(drive_out, "cookies.txt")
            with open(dp, "wb") as df:
                df.write(content_bytes)
            saved_paths.append(dp)
        except Exception:
            pass
    # 3. Kaggle working directory
    for kp in ["/kaggle/working/cookies.txt", "/kaggle/working/ai-translate-agent/cookies.txt"]:
        if os.path.exists(os.path.dirname(kp)):
            try:
                with open(kp, "wb") as kf:
                    kf.write(content_bytes)
                saved_paths.append(kp)
            except Exception:
                pass
    return saved_paths

@app.get("/api/cookies/status")
def get_cookies_status():
    candidates = _get_cookie_paths()
    import glob
    for k_match in glob.glob('/kaggle/input/**/cookies*.txt', recursive=True):
        candidates.append(k_match)

    found_path = None
    file_size = 0
    mtime = None
    has_youtube = False
    cookie_count = 0

    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 10:
            found_path = c
            file_size = os.path.getsize(c)
            try:
                mtime = time.ctime(os.path.getmtime(c))
                with open(c, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                has_youtube = "youtube.com" in text.lower()
                cookie_count = len([line for line in text.splitlines() if line.strip() and not line.startswith("#")])
            except Exception:
                pass
            break

    return {
        "installed": bool(found_path),
        "path": found_path,
        "size_bytes": file_size,
        "size_kb": round(file_size / 1024, 2),
        "has_youtube": has_youtube,
        "cookie_count": cookie_count,
        "last_modified": mtime
    }

@app.post("/api/cookies/save")
def save_cookies_text(req: CookieSaveRequest):
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Cookies content is empty")
    content_bytes = content.encode("utf-8")
    saved_paths = _save_cookie_content(content_bytes)
    return {
        "success": True,
        "message": f"Cookies saved successfully to {len(saved_paths)} location(s)!",
        "saved_paths": saved_paths,
        "bytes": len(content_bytes)
    }

@app.delete("/api/cookies")
def delete_cookies():
    deleted = []
    for c in _get_cookie_paths():
        if os.path.exists(c):
            try:
                os.remove(c)
                deleted.append(c)
            except Exception:
                pass
    return {"success": True, "deleted": deleted}

@app.post("/api/upload")
async def upload_file(video: UploadFile = File(...)):
    if not video.filename:
        raise HTTPException(status_code=400, detail="No selected file")

    import re as _re
    def _secure_filename(fname: str) -> str:
        """Stdlib-based secure_filename: strips unsafe chars, no werkzeug needed."""
        fname = os.path.basename(fname).strip()
        fname = _re.sub(r'[^\w\-_. ]', '_', fname)
        fname = fname.strip('. ')
        return fname or "upload"

    filename = _secure_filename(video.filename)
    # Support automatic YouTube cookies.txt installation
    if filename.lower() in ["cookies.txt", "cookie.txt"] or filename.lower().endswith(".txt"):
        content = await video.read()
        if b"youtube" in content.lower() or b"# Netscape" in content or b"# HTTP Cookie File" in content:
            with open("cookies.txt", "wb") as f:
                f.write(content)
            os.makedirs("assets", exist_ok=True)
            with open(os.path.join("assets", "cookies.txt"), "wb") as f:
                f.write(content)
            drive_out = "/content/drive/MyDrive/MovieRecapOutputs"
            if os.path.exists(drive_out):
                try:
                    with open(os.path.join(drive_out, "cookies.txt"), "wb") as df:
                        df.write(content)
                    print("[*] Upload: cookies.txt permanently saved to Google Drive!")
                except Exception:
                    pass
            for kp in ["/kaggle/working/cookies.txt", "/kaggle/working/ai-translate-agent/cookies.txt"]:
                if os.path.exists(os.path.dirname(kp)):
                    try:
                        with open(kp, "wb") as kf:
                            kf.write(content)
                        print(f"[*] Upload: cookies.txt saved to {kp}!")
                    except Exception:
                        pass
            print("[*] Upload: cookies.txt installed successfully into root and assets/!")
            return {"success": True, "filename": "cookies.txt", "message": "YouTube cookies installed successfully!"}

    ext = os.path.splitext(filename)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File is not a supported video format or cookies.txt")
        
    os.makedirs("movies", exist_ok=True)
    save_path = os.path.join("movies", filename)
    with open(save_path, "wb") as f:
        # BUG-M3 Fix: Stream in 1MB chunks — avoids loading a 4GB file entirely into RAM
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


    return {"success": True, "filename": filename}

@app.post("/api/start")
async def start_pipeline(req: StartRequest):
    input_source = req.input
    language = req.language or 'burmese'
    subtitle_mode = req.subtitle_mode or 'burn'
    subtitle_style = req.subtitle_style or 'box_black'
    resolution = req.resolution or '1080p'
    tts_engine = req.tts_engine
    custom_thumb_title = req.custom_thumb_title
    watermark_enabled = req.watermark_enabled
    watermark_text = req.watermark_text
    watermark_opacity = req.watermark_opacity
    
    # Resolve video_format (supports backwards-compatible reels_enabled toggle)
    video_format = req.video_format or ("both" if req.reels_enabled else "16:9")

    if not input_source:
        raise HTTPException(status_code=400, detail="No input provided")
    
    _cleanup_old_jobs()
    with jobs_lock:
        job_id = str(uuid.uuid4())
        is_running = _has_running_job()
        initial_status = "running" if not is_running else "queued"
        initial_phase = "Starting..." if not is_running else "Queued in background"
        jobs[job_id] = {
            "status": initial_status,
            "phase": initial_phase,
            "buffer": None,
            "created_at": time.time(),
            "name": str(input_source),
            "source": str(input_source),
            "language": str(language),
            "tts_engine": str(tts_engine or "edge_tts")
        }
        try:
            create_job(job_id, str(input_source), phase=initial_phase, status=initial_status)
        except Exception:
            pass

    if req.engine_mode == "hardsub":
        job_entry = {
            "job_id": job_id,
            "target": hardsub_worker,
            "args": (
                job_id,
                input_source,
                req.project_name,
                req.source_language or "auto",
                req.force_whisper or False,
                video_format,
                resolution,
                subtitle_style,
                req.blur_mode or "auto",
                req.mirror or False,
                req.color_grading if req.color_grading is not None else True,
                req.blur_height,
                req.audio_anti_copyright or False,
            ),
            "name": str(req.project_name or input_source),
            "source": str(input_source),
            "language": str(req.source_language or "auto"),
            "engine_mode": "hardsub",
            "created_at": time.time()
        }
    elif req.engine_mode == "subtitle":
        job_entry = {
            "job_id": job_id,
            "target": subtitle_worker,
            "args": (
                job_id,
                input_source,
                req.project_name,
                req.source_language or "auto",
                req.force_whisper or False,
            ),
            "name": str(req.project_name or input_source),
            "source": str(input_source),
            "language": str(req.source_language or "auto"),
            "engine_mode": "subtitle",
            "created_at": time.time()
        }
    else:
        job_entry = {
            "job_id": job_id,
            "target": pipeline_worker,
            "args": (
            job_id,
            input_source,
            language,
            subtitle_mode,
            resolution,
            tts_engine,
            custom_thumb_title,
            watermark_enabled,
            watermark_text,
            watermark_opacity,
            req.reels_enabled,
            video_format,
            subtitle_style,
            req.thumbnail_intro,
            req.source_language or "auto",
            req.skip_demucs or False,
            req.detect_scenes or False,
            req.resume if req.resume is not None else True,
            req.tts_voice,
            req.script_engine or "recap",
            req.trim_end,
            req.no_smart_trim or False,
            req.outro_card or False,
        ),
        "name": str(input_source),
        "source": str(input_source),
        "language": str(language),
        "tts_engine": str(tts_engine or "edge_tts"),
        "created_at": time.time()
    }

    with queue_lock:
        if not is_running:
            t = threading.Thread(target=job_entry["target"], args=job_entry["args"], daemon=True)
            t.start()
            return {"job_id": job_id, "status": "running"}
        else:
            job_queue.append(job_entry)
            _ensure_queue_dispatcher()
            pos = len(job_queue)
            return {"job_id": job_id, "status": "queued", "position": pos, "message": f"Job queued at position #{pos}"}

@app.post("/api/batch/start")
async def start_batch_pipeline(req: BatchStartRequest):
    inputs = req.inputs
    language = req.language or 'burmese'
    subtitle_mode = req.subtitle_mode or 'burn'
    subtitle_style = req.subtitle_style or 'box_black'
    resolution = req.resolution or '1080p'
    tts_engine = req.tts_engine
    custom_thumb_title = req.custom_thumb_title
    watermark_enabled = req.watermark_enabled
    watermark_text = req.watermark_text
    watermark_opacity = req.watermark_opacity
    video_format = req.video_format or ("both" if req.reels_enabled else "16:9")

    if not inputs or not all(isinstance(item, str) and item.strip() for item in inputs):
        raise HTTPException(status_code=400, detail="No inputs provided for batch mode")
        
    _cleanup_old_jobs()
    with jobs_lock:
        job_id = str(uuid.uuid4())
        is_running = _has_running_job()
        initial_status = "running" if not is_running else "queued"
        initial_phase = "Batch Mode Starting..." if not is_running else "Batch Queued in background"
        jobs[job_id] = {
            "status": initial_status,
            "phase": initial_phase,
            "buffer": None,
            "created_at": time.time(),
            "name": f"Batch ({len(inputs)} items)",
            "source": f"Batch ({len(inputs)} items)",
            "language": str(language),
            "tts_engine": str(tts_engine or "edge_tts")
        }
        try:
            create_job(job_id, f"Batch ({len(inputs)} items)", phase=initial_phase, status=initial_status)
        except Exception:
            pass

    job_entry = {
        "job_id": job_id,
        "target": batch_worker,
        "args": (
            job_id,
            inputs,
            language,
            subtitle_mode,
            resolution,
            tts_engine,
            custom_thumb_title,
            watermark_enabled,
            watermark_text,
            watermark_opacity,
            req.reels_enabled,
            video_format,
            subtitle_style,
            req.thumbnail_intro,
            req.source_language or "auto",
            req.skip_demucs or False,
            req.detect_scenes or False,
            req.resume if req.resume is not None else True,
            req.tts_voice,
            req.script_engine or "recap",
            req.engine_mode or "recap",
            req.blur_mode or "auto",
            req.blur_height,
            req.mirror or False,
            req.color_grading if req.color_grading is not None else True,
            req.audio_anti_copyright or False,
            req.force_whisper or False,
        ),
        "name": f"Batch [{req.engine_mode.upper() if req.engine_mode else 'RECAP'}] ({len(inputs)} items)",
        "source": f"Batch ({len(inputs)} items)",
        "language": str(language),
        "tts_engine": str(tts_engine or "edge_tts"),
        "created_at": time.time()
    }

    with queue_lock:
        if not is_running:
            t = threading.Thread(target=job_entry["target"], args=job_entry["args"], daemon=True)
            t.start()
            return {"job_id": job_id, "status": "running"}
        else:
            job_queue.append(job_entry)
            _ensure_queue_dispatcher()
            pos = len(job_queue)
            return {"job_id": job_id, "status": "queued", "position": pos, "message": f"Batch job queued at position #{pos}"}

@app.get("/api/queue")
def get_job_queue():
    """Returns list of currently queued jobs and positions."""
    with queue_lock:
        items = []
        for idx, item in enumerate(job_queue):
            kwargs = item.get("kwargs", {})
            items.append({
                "job_id": item["job_id"],
                "name": item.get("name", "video"),
                "source": item.get("source") or kwargs.get("input") or item.get("name", "video"),
                "language": item.get("language") or kwargs.get("language", "burmese"),
                "tts_engine": item.get("tts_engine") or kwargs.get("tts_engine", "edge_tts"),
                "position": idx + 1,
                "status": "queued",
                "created_at": item.get("created_at")
            })
    active_info = get_active_job()
    return {
        "queue": items,
        "total": len(items),
        "queue_length": len(items),
        "active_job": active_info if active_info and active_info.get("job_id") else None
    }

@app.delete("/api/queue/{job_id}")
def delete_from_queue(job_id: str):
    """Cancels and removes a pending job from the FIFO queue."""
    removed = False
    with queue_lock:
        for idx, item in enumerate(list(job_queue)):
            if item["job_id"] == job_id:
                job_queue.pop(idx)
                removed = True
                break
    with jobs_lock:
        if job_id in jobs and jobs[job_id].get("status") == "queued":
            jobs[job_id]["status"] = "cancelled"
            jobs[job_id]["phase"] = "Cancelled from queue"
            try:
                update_job(job_id, status="cancelled", phase="Cancelled from queue")
            except Exception:
                pass
    if removed:
        return {"success": True, "message": f"Job {job_id} removed from queue."}
    raise HTTPException(status_code=404, detail="Job not found in queue")

@app.post("/api/stop")
@app.post("/api/cancel")
@app.post("/api/cancel/{job_id}")
async def stop_pipeline(job_id: Optional[str] = None):
    """Force-stop any currently running single or batch pipeline job."""
    stopped_count = 0
    os.environ["CURRENT_JOB_CANCELLED"] = "1"
    
    with jobs_lock:
        if job_id:
            target_jids = [job_id]
        else:
            target_jids = [jid for jid, j in jobs.items() if j.get("status") in ("running", "queued")]
            
        for jid in target_jids:
            if jid in jobs:
                cancel_events.setdefault(jid, threading.Event()).set()
                jobs[jid]["status"] = "cancelled"
                jobs[jid]["phase"] = "Stopped by user"
                stopped_count += 1
                try:
                    update_job(jid, status="cancelled", phase="Stopped by user")
                except Exception:
                    pass
                print(f"\n🛑 [STOP] Force-stop signal received! Cancelled job {jid}.")

    with queue_lock:
        if job_id:
            job_queue[:] = [q for q in job_queue if q.get("job_id") != job_id]
        else:
            for q in list(job_queue):
                q_jid = q.get("job_id")
                with jobs_lock:
                    if q_jid in jobs:
                        jobs[q_jid]["status"] = "cancelled"
                        jobs[q_jid]["phase"] = "Stopped by user"
            job_queue.clear()

    # Safely terminate child processes (ffmpeg, ffprobe, yt-dlp, demucs) spawned by THIS process tree only
    try:
        import psutil
        current_process = psutil.Process()
        children = current_process.children(recursive=True)
        for child in children:
            try:
                cname = child.name().lower()
                if any(x in cname for x in ["ffmpeg", "ffprobe", "yt-dlp", "demucs"]):
                    child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

    return {"success": True, "stopped_count": stopped_count, "message": "Pipeline force-stopped successfully."}

@app.get("/api/config/branding")
async def get_branding_config():
    c = cfg.load_config()
    return {
        "watermark": c.get("watermark", {}),
        "thumbnail_intro": c.get("thumbnail_intro", {"enabled": False, "duration_sec": 3.0}),
    }

@app.post("/api/config/branding")
async def save_branding_config(req: BrandingConfigRequest):
    c = cfg.load_config()
    if "watermark" not in c:
        c["watermark"] = {}
    c["watermark"]["enabled"] = req.watermark_enabled
    c["watermark"]["text"] = req.watermark_text
    c["watermark"]["opacity"] = req.watermark_opacity
    c["watermark"]["margin"] = req.watermark_margin
    c["watermark"]["font_size"] = req.watermark_font_size
    cfg.save_config(c)
    return {"status": "ok", "watermark": c["watermark"]}

@app.get("/api/config/subtitles")
async def get_subtitle_config():
    """Returns available subtitle style presets and current active setting."""
    c = cfg.load_config()
    sub_cfg = c.get("subtitle_overlay", {})
    return {
        "presets": list(SUBTITLE_PRESETS.values()),
        "current_preset": sub_cfg.get("style_preset", "box_black"),
        "config": sub_cfg,
    }

@app.post("/api/config/subtitles")
async def save_subtitle_config(req: SubtitleConfigRequest):
    """Saves chosen subtitle style preset into config.json."""
    if req.preset not in SUBTITLE_PRESETS:
        raise HTTPException(status_code=400, detail="Unknown preset ID")
    c = cfg.load_config()
    if "subtitle_overlay" not in c:
        c["subtitle_overlay"] = {}
    c["subtitle_overlay"]["style_preset"] = req.preset
    cfg.save_config(c)
    return {"status": "ok", "preset": req.preset}

@app.get("/api/stream/{job_id}")
async def stream_job_logs(job_id: str, request: Request):
    """Server-Sent Events (SSE) stream for zero-latency live logs and progress updates."""
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()
        sub_item = (q, loop)
        if job_id not in thread_stdout.subscribers:
            thread_stdout.subscribers[job_id] = []
        thread_stdout.subscribers[job_id].append(sub_item)

        try:
            with jobs_lock:
                job = jobs.get(job_id, {})
                buf = job.get('buffer') or thread_stdout.buffers.get(job_id)
                initial_content = buf.getvalue() if buf else ""

            if initial_content:
                lines = [l for l in initial_content.split('\n') if l.strip()]
                for l in lines[-30:]:
                    yield {"event": "log", "data": json.dumps({"line": l})}

            while True:
                if await request.is_disconnected():
                    break

                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=1.5)
                    lines = chunk.replace('\r', '\n').split('\n')
                    for l in lines:
                        if l.strip():
                            current_phase = "Running..."
                            batch_status = None
                            if '--- [Phase' in l or '--- [DONE]' in l:
                                current_phase = l.strip().strip('-').strip()
                            elif '[DONE]' in l:
                                current_phase = 'Done'
                            elif 'Downloading:' in l or 'Downloading video' in l:
                                current_phase = 'Downloading Video...'

                            m = re.search(r'\[(\d+)/(\d+)\] Processing:\s*(.*)', l)
                            if m: batch_status = f"Queue: {m.group(1)} of {m.group(2)} ({m.group(3)})"

                            with jobs_lock:
                                cur_status = jobs.get(job_id, {}).get('status', 'running')

                            yield {
                                "event": "log",
                                "data": json.dumps({
                                    "line": l,
                                    "phase": current_phase,
                                    "batch_status": batch_status,
                                    "status": cur_status
                                })
                            }
                except asyncio.TimeoutError:
                    # Cloudflare keepalive ping to prevent proxy/tunnel dropping the connection
                    yield {"comment": "ping"}

                with jobs_lock:
                    current_job = jobs.get(job_id)
                    if not current_job:
                        break
                    job_status = current_job.get('status')

                if job_status in ('done', 'error', 'cancelled'):
                    # Drain any pending log chunks in queue before sending done event
                    while not q.empty():
                        try:
                            chunk = q.get_nowait()
                            lines = chunk.replace('\r', '\n').split('\n')
                            for l in lines:
                                if l.strip():
                                    yield {
                                        "event": "log",
                                        "data": json.dumps({
                                            "line": l,
                                            "phase": "Done" if job_status == "done" else "Completed",
                                            "batch_status": None,
                                            "status": job_status
                                        })
                                    }
                        except Exception:
                            break

                    yield {
                        "event": "done",
                        "data": json.dumps({"status": job_status, "error": current_job.get("error")})
                    }
                    break

        finally:
            subs = thread_stdout.subscribers.get(job_id, [])
            if sub_item in subs:
                subs.remove(sub_item)
            if not subs:
                thread_stdout.subscribers.pop(job_id, None)

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@app.get("/api/status")
async def latest_status_endpoint():
    with jobs_lock:
        if not jobs:
            return {"status": "idle", "phase": "Idle", "progress": 0, "job_id": None, "log": []}
        latest_id = list(jobs.keys())[-1]
    return await status_endpoint(latest_id)

@app.get("/api/status/{job_id}")
async def status_endpoint(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = jobs[job_id]
        
    buffer = job.get('buffer') or thread_stdout.buffers.get(job_id)
    log_lines = []
    current_phase = job.get('phase', 'Starting...')
    batch_status = None
    phase_timings = {}
    
    if buffer:
        content = buffer.getvalue()
        lines = [line for line in content.split('\n') if line.strip()]
        log_lines = lines[-35:]

        for line in reversed(lines):
            if '--- [Phase' in line or '--- [DONE]' in line:
                current_phase = line.strip().strip('-').strip()
                break
            if '[DONE]' in line:
                current_phase = 'Done'
                break
            if 'Downloading:' in line or 'Downloading video' in line:
                current_phase = 'Downloading Video...'
                break

        for line in reversed(lines):
            m = re.search(r'\[(\d+)/(\d+)\] Processing:\s*(.*)', line)
            if m:
                batch_status = f"Queue: {m.group(1)} of {m.group(2)} ({m.group(3)})"
                break
            m2 = re.search(r'\[(\d+)/(\d+)\] Downloading:', line)
            if m2 and not batch_status:
                batch_status = f"Downloading: {m2.group(1)} of {m2.group(2)}"
                break

        # Extract live phase completion durations
        for line in lines:
            if '[⏱️ TIMING]' in line:
                tm = re.search(r'\[⏱️ TIMING\] (Phase [^f]+) finished in ([\d\.]+)s', line)
                if tm:
                    phase_timings[tm.group(1).strip()] = float(tm.group(2))

    created_at = job.get("created_at")
    elapsed_sec = round(time.time() - created_at, 1) if created_at else None

    # Compute progress integer (0-100) from phase name for frontend progress bar

    progress_map = {
        "Step 1": 15, "Step 2": 35, "Step 3": 50, "Step 4": 65,
        "Step 5": 85, "Step 6": 95, "Step 7": 98,
        "Phase 1": 5, "Phase 2": 20, "Phase 3": 25, "Phase 4": 40,
        "Phase 5": 60, "Phase 6": 85, "Phase 6b": 95, "Phase 7": 98,
        "Done": 100, "Downloading": 3, "Starting": 1,
    }
    progress = 0
    if job["status"] == "done":
        progress = 100
    elif job["status"] in ("error", "cancelled"):
        progress = 0
    else:
        for phase_key, pval in progress_map.items():
            if phase_key.lower() in current_phase.lower():
                progress = pval
                break

    return {
        "job_id": job_id,
        "status": job["status"],
        "phase": current_phase,
        "progress": progress,
        "batch_status": batch_status,
        "elapsed_sec": elapsed_sec,
        "phase_timings": phase_timings,
        "log": log_lines,
        "error": job.get("error"),
    }


@app.get("/api/outputs")
def list_outputs():
    metadata = list_movie_states("outputs")
    outputs_dir = "outputs"
    if not os.path.exists(outputs_dir):
        return {"metadata": metadata, "outputs": {}}

    result = {}
    for root, dirs, files in os.walk(outputs_dir):
        if os.path.basename(root) in ["temp", "voiceover"]:
            dirs[:] = []
            continue

        if "state.json" not in files:
            continue

        rel_dir = os.path.relpath(root, outputs_dir).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        entry = {"files": [], "progress": 100, "phase": "Done", "total_duration": "", "phase_durations": {}, "engine_type": "recap"}
        for f in sorted(files):
            if f == "state.json":
                try:
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as sf:
                        state_data = json.load(sf)
                        entry["progress"] = state_data.get("progress", 100)
                        entry["phase"] = state_data.get("current_phase", "Done")
                        entry["total_duration"] = state_data.get("total_duration_formatted", "")
                        entry["total_duration_sec"] = state_data.get("total_duration_sec", 0.0)
                        entry["phase_durations"] = state_data.get("phase_durations", {})
                        entry["engine_type"] = state_data.get("engine_type", "subtitle" if any("subtitle_burmese" in x for x in files) else "recap")
                        entry["total_records"] = state_data.get("total_records")
                except Exception:
                    pass
                continue
            entry["files"].append(posixpath.join(rel_dir, f) if rel_dir else f)

        result[rel_dir or os.path.basename(root)] = entry
        dirs[:] = []

    return {"metadata": metadata, "outputs": result}

@app.get("/api/logs/{movie_name:path}")
def get_movie_logs(movie_name: str):
    safe_name = os.path.normpath(movie_name).strip(" /\\.")
    outputs_dir = os.path.abspath("outputs")
    log_path = os.path.normpath(os.path.join(outputs_dir, safe_name, "pipeline.log"))
    if os.path.commonpath([outputs_dir, log_path]) != outputs_dir:
        raise HTTPException(status_code=400, detail="Invalid log path")
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found for this movie")
    
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return PlainTextResponse(content)

@app.get("/api/outputs/file")
@app.get("/api/download")
def serve_output(path: str = Query("")):
    rel_path = path
    if not rel_path:
        raise HTTPException(status_code=400, detail="No file path specified")

    safe_path = os.path.normpath(rel_path)
    if safe_path.startswith('..') or os.path.isabs(safe_path):
        raise HTTPException(status_code=400, detail="Invalid file path")

    outputs_dir = os.path.abspath("outputs")
    full_path = os.path.normpath(os.path.join(outputs_dir, safe_path))
    if os.path.commonpath([outputs_dir, full_path]) != outputs_dir:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    if os.path.isdir(full_path):
        files = [
            {"name": f, "url": f"/api/outputs/file?path={quote(os.path.join(rel_path, f))}"}
            for f in sorted(os.listdir(full_path))
        ]
        return {"directory": rel_path, "files": files}

    return FileResponse(full_path)

@app.get("/api/download/zip")
@app.get("/api/outputs/zip")
def download_project_zip(movie: str = Query("")):
    """Packages all finished recap assets for a given movie into a single fast-downloadable .zip archive."""
    if not movie:
        raise HTTPException(status_code=400, detail="Movie project name required")

    safe_movie = os.path.normpath(movie).strip("/\\")
    if safe_movie.startswith("..") or os.path.isabs(safe_movie):
        raise HTTPException(status_code=400, detail="Invalid movie directory")

    outputs_dir = os.path.abspath("outputs")
    proj_dir = os.path.normpath(os.path.join(outputs_dir, safe_movie))
    if os.path.commonpath([outputs_dir, proj_dir]) != outputs_dir or not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Movie project output directory not found")

    from starlette.background import BackgroundTask
    temp_dir = os.path.abspath("temp")
    os.makedirs(temp_dir, exist_ok=True)
    clean_base = re.sub(r'[^a-zA-Z0-9_\-]', '_', safe_movie)[:60].strip('_')
    zip_filename = f"{clean_base}_Bundle.zip"
    unique_suffix = uuid.uuid4().hex[:8]
    zip_path = os.path.join(temp_dir, f"{clean_base}_{unique_suffix}_bundle.zip")

    excluded_names = {"state.json", "checkpoint.json", "temp", "temp_test_dl"}

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(proj_dir):
            dirs[:] = [d for d in dirs if d not in ["voiceover", "temp", "__pycache__"]]
            for f in sorted(files):
                if f in excluded_names or f.endswith(".tmp") or f.endswith(".part"):
                    continue
                file_full = os.path.join(root, f)
                rel_in_zip = os.path.relpath(file_full, proj_dir)
                # Store pre-compressed video files directly for instant 0-second zipping; compress text/subtitles
                if f.lower().endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                    zf.write(file_full, arcname=rel_in_zip, compress_type=zipfile.ZIP_STORED)
                else:
                    zf.write(file_full, arcname=rel_in_zip, compress_type=zipfile.ZIP_DEFLATED)

    def _cleanup_temp_zip(p: str):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_filename,
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
        background=BackgroundTask(_cleanup_temp_zip, zip_path)
    )

@app.get("/api/movies")
def list_movies():
    movies_dir = "movies"
    if not os.path.exists(movies_dir):
        return []
    files = [f for f in os.listdir(movies_dir) if f.lower().endswith(VIDEO_EXTENSIONS)]
    return sorted(files)

@app.delete("/api/delete/cache")
async def clear_cache():
    cleared = 0
    for d in ["temp", "voiceover"]:
        if os.path.exists(d):
            for item in os.listdir(d):
                p = os.path.join(d, item)
                try:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                    cleared += 1
                except Exception:
                    pass

    for root, dirs, files in os.walk('.'):
        for d in list(dirs):
            if d == '__pycache__':
                try:
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)
                    cleared += 1
                except Exception:
                    pass

    # Clean any MoviePy intermediate temp files in root/cwd
    for f in os.listdir("."):
        if "TEMP_MPY" in f and (f.endswith(".mp4") or f.endswith(".wav")):
            try:
                os.remove(f)
                cleared += 1
            except Exception:
                pass

    return {"success": True, "cleared_items": cleared}

@app.api_route("/api/config", methods=["GET", "POST"])
async def handle_config(request: Request):
    import brain.config as cfg
    config_data = cfg.load_config()
    if request.method == 'POST':
        data = await request.json() or {}
        if "mirror_video" in data:
            if "copyright_protection" not in config_data:
                config_data["copyright_protection"] = {}
            config_data["copyright_protection"]["mirror_video"] = bool(data["mirror_video"])
            cfg.save_config(config_data)
        if "tts_engine" in data:
            if "voice" not in config_data:
                config_data["voice"] = {}
            config_data["voice"]["engine"] = str(data["tts_engine"]).strip().lower()
            cfg.save_config(config_data)
        if "thumbnail_intro" in data:
            if "thumbnail_intro" not in config_data:
                config_data["thumbnail_intro"] = {}
            if isinstance(data["thumbnail_intro"], dict):
                config_data["thumbnail_intro"].update(data["thumbnail_intro"])
            elif isinstance(data["thumbnail_intro"], bool):
                config_data["thumbnail_intro"]["enabled"] = data["thumbnail_intro"]
            cfg.save_config(config_data)
        if "audio_ducking" in data:
            if "audio_ducking" not in config_data:
                config_data["audio_ducking"] = {}
            if isinstance(data["audio_ducking"], dict):
                config_data["audio_ducking"].update(data["audio_ducking"])
            elif isinstance(data["audio_ducking"], bool):
                config_data["audio_ducking"]["enabled"] = data["audio_ducking"]
            cfg.save_config(config_data)
        if "use_demucs" in data:
            if "pipeline" not in config_data:
                config_data["pipeline"] = {}
            config_data["pipeline"]["use_demucs"] = bool(data["use_demucs"])
            cfg.save_config(config_data)
        if "scene_detection" in data:
            if "pipeline" not in config_data:
                config_data["pipeline"] = {}
            config_data["pipeline"]["scene_detection"] = bool(data["scene_detection"])
            cfg.save_config(config_data)
        if "script_engine" in data:
            if "pipeline" not in config_data:
                config_data["pipeline"] = {}
            config_data["pipeline"]["script_engine"] = str(data["script_engine"]).strip().lower()
            cfg.save_config(config_data)
        public_config = json.loads(json.dumps(config_data))
        public_config.get("gemini", {}).pop("api_keys", None)
        return {"success": True, "config": public_config}
    else:
        public_config = json.loads(json.dumps(config_data))
        public_config.get("gemini", {}).pop("api_keys", None)
        return public_config

@app.get("/api/keys/status")
def get_key_status():
    try:
        config_data = cfg.load_config()
        gemini_cfg = config_data.get("gemini", {})
        configured_keys = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEY") or []
        if isinstance(configured_keys, str):
            configured_keys = [k.strip() for k in configured_keys.split(",") if k.strip()]
        elif not isinstance(configured_keys, list):
            configured_keys = []
            
        from brain.tracker import load_usage_db, get_google_utc_date
        db = load_usage_db()
        recorded_keys = db.get("keys", {})
        current_utc = get_google_utc_date()
        
        def ping_google_key(key):
            key_str = str(key).strip()
            if not key_str:
                return "EMPTY", 0
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Recap/2.2",
                        "x-goog-api-key": key_str
                    },
                    method="GET"
                )
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    if resp.status == 200:
                        return "ONLINE", 200
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    return "RATE LIMITED (429)", 429
                elif e.code in [400, 401, 403]:
                    return "INVALID KEY", e.code
                return f"HTTP {e.code}", e.code
            except Exception:
                return "UNREACHABLE", 0
            return "UNKNOWN", 0

        key_statuses = []
        total_remaining = 0
        
        workers = min(10, max(1, len(configured_keys)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            ping_results = list(executor.map(ping_google_key, configured_keys))

        for idx, key in enumerate(configured_keys):
            if not key or not str(key).strip(): continue
            key_str = str(key).strip()
            masked = key_str[:6] + "..." + key_str[-4:] if len(key_str) > 10 else key_str
            
            live_state, http_code = ping_results[idx]
            kdata = recorded_keys.get(masked, {})
            
            model_limits = gemini_cfg.get("model_limits", {})
            models_data = kdata.get("models", {})
            
            model_stats = []
            for m_name, m_limit in model_limits.items():
                used = models_data.get(m_name, {}).get("used_today", 0)
                if kdata.get("utc_date") != current_utc:
                    used = 0
                remaining = max(0, int(m_limit) - used)
                total_remaining += remaining
                model_stats.append({
                    "name": m_name,
                    "used_today": used,
                    "limit": int(m_limit),
                    "remaining": remaining
                })
                
            key_statuses.append({
                "key": masked,
                "live_status": live_state,
                "http_code": http_code,
                "models": model_stats
            })
            
        hardware = detect_hardware_encoder()
        return {
            "total_keys": len(key_statuses),
            "total_remaining_requests": total_remaining,
            "daily_limit_per_key": int(gemini_cfg.get("daily_limit_per_key", 20)),
            "hardware_encoder": hardware,
            "keys": key_statuses
        }
    except Exception as e:
        print(f"[ERROR] /api/keys/status failed: {e}")
        return {
            "total_keys": 0,
            "total_remaining_requests": 0,
            "daily_limit_per_key": 20,
            "hardware_encoder": {"codec": "libx264", "label": "CPU Multi-Core", "type": "cpu"},
            "keys": [],
            "error": str(e)
        }

@app.delete("/api/delete/{folder_type}/{item_name:path}")
async def delete_item(folder_type: str, item_name: str):
    target_path = _safe_child_path(folder_type, item_name)
    if not target_path:
        raise HTTPException(status_code=400, detail="Invalid target")
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Item not found")
        
    try:
        if os.path.isdir(target_path):
            shutil.rmtree(target_path, ignore_errors=True)
        else:
            os.remove(target_path)
            
        if folder_type == "outputs":
            temp_path = os.path.join("temp", item_name)
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)
            try:
                delete_movie_state(item_name)
            except Exception as e:
                print(f"[WARN] Could not remove output DB entry for {item_name}: {e}")
                
        print(f"[*] WebUI: Successfully deleted {folder_type}/{item_name}")
        return {"success": True, "message": f"Deleted {item_name}"}
    except Exception as e:
        print(f"[!] WebUI: Delete failed ({e})")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/delete_all/{folder_type}")
async def delete_all(folder_type: str, confirm: bool = False):
    with jobs_lock:
        if _has_running_job():
            raise HTTPException(status_code=409, detail="Cannot delete files while a pipeline job is running.")
    if not confirm:
        raise HTTPException(status_code=400, detail="Mass deletion requires 'confirm=true' parameter.")
    if folder_type not in {'movies', 'outputs', 'temp', 'all'}:
        raise HTTPException(status_code=400, detail="Invalid target")
    
    targets = ['movies', 'outputs', 'temp'] if folder_type == 'all' else [folder_type]
    deleted = 0
    try:
        for target_folder in targets:
            root = os.path.abspath(target_folder)
            if not os.path.isdir(root):
                continue
            for item_name in os.listdir(root):
                if target_folder == 'outputs' and item_name in ['api_usage_db.json', 'movie_metadata.db']:
                    continue
                    
                target = _safe_child_path(target_folder, item_name)
                if not target:
                    continue
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
                deleted += 1
        return {"success": True, "deleted_items": deleted}
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Could not delete all items: {error}")

@app.post("/api/rename/movie")
async def rename_movie(req: RenameRequest):
    old_name = os.path.basename(req.old_name.strip())
    new_name = os.path.basename(req.new_name.strip())
    if not old_name or not new_name or old_name != req.old_name or new_name != req.new_name:
        raise HTTPException(status_code=400, detail="Use a filename only; folders are not allowed.")
    if not old_name.lower().endswith(VIDEO_EXTENSIONS) or not new_name.lower().endswith(VIDEO_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Movie files must use a supported video extension.")
        
    source = _safe_child_path('movies', old_name)
    destination = _safe_child_path('movies', new_name)
    if not source or not destination or not os.path.isfile(source):
        raise HTTPException(status_code=404, detail="Source movie was not found.")
    if os.path.exists(destination):
        raise HTTPException(status_code=409, detail="A movie with that name already exists.")
    try:
        os.replace(source, destination)
        return {"success": True, "name": new_name}
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Could not rename movie: {error}")

@app.get("/api/keys")
@app.get("/api/keys/list")
def list_raw_keys():
    try:
        config_data = cfg.load_config()
        gemini_cfg = config_data.get("gemini", {})
        keys = gemini_cfg.get("api_keys", [])
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        elif not isinstance(keys, list):
            keys = []
        if not keys and os.getenv("GEMINI_API_KEY"):
            keys = [k.strip() for k in os.getenv("GEMINI_API_KEY", "").split(",") if k.strip()]
        masked_keys = [k[:6] + "..." + k[-4:] if len(k) > 10 else k for k in keys]
        return {'keys': masked_keys, 'count': len(masked_keys)}
    except Exception as e:
        print(f"[ERROR] /api/keys/list failed: {e}")
        return {'keys': [], 'count': 0, 'error': str(e)}

@app.post("/api/keys/save")
def save_keys(req: SaveKeysRequest):
    try:
        config_data = cfg.load_config()
        existing_keys = config_data.get("gemini", {}).get("api_keys", [])
        if isinstance(existing_keys, str):
            existing_keys = [k.strip() for k in existing_keys.split(",") if k.strip()]
        elif not isinstance(existing_keys, list):
            existing_keys = []

        new_keys = req.keys
        cleaned_keys = []
        for line in new_keys:
            tokens = [t.strip() for t in str(line).replace(',', '\n').split('\n') if t.strip()]
            for k in tokens:
                # If key contains '...', user might have preserved a masked key from the status view.
                # Resolve to the full existing key so real key is never lost!
                if '...' in k:
                    parts = k.split('...')
                    prefix, suffix = parts[0].strip(), parts[-1].strip()
                    matched = None
                    for ek in existing_keys:
                        if ek.startswith(prefix) and ek.endswith(suffix):
                            matched = ek
                            break
                    if matched:
                        k = matched
                    else:
                        continue
                if k and k not in cleaned_keys:
                    cleaned_keys.append(k)
                
        config_data.setdefault("gemini", {})["api_keys"] = cleaned_keys
        cfg.save_config(config_data)
            
        print(f"[*] WebUI: Updated API keys in config.json ({len(cleaned_keys)} keys)")
        # Permanent Google Drive Sync for Colab
        drive_out = "/content/drive/MyDrive/MovieRecapOutputs"
        if os.path.exists(drive_out):
            try:
                import shutil
                shutil.copy2("config.json", os.path.join(drive_out, "config.json"))
                for db_name in ["movie_metadata.db", "database.db"]:
                    for src_path in [os.path.join("outputs", db_name), db_name]:
                        if os.path.exists(src_path):
                            shutil.copy2(src_path, os.path.join(drive_out, db_name))
                print("[*] WebUI: Permanently synced config.json and database to Google Drive!")
            except Exception:
                pass

        return {"success": True, "keys_count": len(cleaned_keys), "keys": cleaned_keys}
    except Exception as e:
        print(f"[ERROR] Failed to save API keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/subtitle/preview/{movie_name:path}")
def preview_subtitle_project(movie_name: str):
    safe_name = os.path.normpath(movie_name).strip(" /\\.")
    outputs_dir = os.path.abspath("outputs")
    proj_dir = os.path.normpath(os.path.join(outputs_dir, safe_name))
    if os.path.commonpath([outputs_dir, proj_dir]) != outputs_dir or not os.path.exists(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")

    srt_file = os.path.join(proj_dir, "05_subtitle_burmese.srt")
    qc_file = os.path.join(proj_dir, "06_quality_check_report.txt")
    if not os.path.exists(qc_file):
        alt_qc = os.path.join(proj_dir, "06_translation_qc_report.txt")
        if os.path.exists(alt_qc):
            qc_file = alt_qc
    txt_file = os.path.join(proj_dir, "04_transcript_burmese.txt")
    json_file = os.path.join(proj_dir, "records_data.json")

    srt_content = ""
    if os.path.exists(srt_file):
        with open(srt_file, "r", encoding="utf-8", errors="replace") as f:
            srt_content = f.read()

    qc_content = ""
    if os.path.exists(qc_file):
        with open(qc_file, "r", encoding="utf-8", errors="replace") as f:
            qc_content = f.read()

    txt_content = ""
    if os.path.exists(txt_file):
        with open(txt_file, "r", encoding="utf-8", errors="replace") as f:
            txt_content = f.read()

    raw_records = []
    if os.path.exists(json_file):
        try:
            with open(json_file, "r", encoding="utf-8", errors="replace") as f:
                raw_records = json.load(f)
        except Exception:
            pass

    normalized_records = []
    for r in raw_records[:300]:
        s_time = r.get("start_s") if r.get("start_s") is not None else r.get("start_time", 0.0)
        e_time = r.get("end_s") if r.get("end_s") is not None else r.get("end_time", 0.0)
        orig = r.get("original") or r.get("original_text") or ""
        burm = r.get("burmese") or r.get("translated_text") or ""
        normalized_records.append({
            "start_time": float(s_time or 0.0),
            "end_time": float(e_time or 0.0),
            "original_text": str(orig),
            "translated_text": str(burm),
            "speaker_gender": r.get("speaker_gender") or r.get("gender") or "",
        })

    return {
        "project": safe_name,
        "srt": srt_content,
        "txt": txt_content,
        "qc": qc_content,
        "srt_content": srt_content,
        "qc_report": qc_content,
        "transcript_burmese": txt_content,
        "records": normalized_records,
        "total_records": len(raw_records)
    }

if __name__ == '__main__':
    import uvicorn, argparse
    parser = argparse.ArgumentParser(description="AI Movie Recap Web UI Server")
    parser.add_argument("--host", type=str, default=None, help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    args, _ = parser.parse_known_args()

    default_host = "0.0.0.0" if ("COLAB_GPU" in os.environ or "KAGGLE_KERNEL_RUN_TYPE" in os.environ or "COLAB_RELEASE_TAG" in os.environ) else "127.0.0.1"
    host = args.host or os.getenv("HOST", default_host)
    port = args.port or int(os.getenv("PORT", 5000))
    uvicorn.run(app, host=host, port=port, log_level='info')
