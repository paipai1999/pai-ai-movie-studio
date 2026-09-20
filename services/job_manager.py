"""
Job Manager & Process Tracking Service (အလုပ်များနှင့် Process စီမံခန့်ခွဲမှု ဝန်ဆောင်မှု)
===================================================================================
Maintains in-memory state of all active, queued, and completed video generation
jobs, along with their associated OS process trees, cancel events, and SSE log queues.

ဤ module သည် လက်ရှိ လည်ပတ်နေသော၊ တန်းစီနေသော နှင့် ပြီးစီးသွားသော အလုပ်များ၏
Status၊ Process PIDs၊ အရေးပေါ် ရပ်တန့်နိုင်မှုနှင့် SSE Terminal Logs များကို စီမံပေးပါသည်။
"""

import os
import sys
import time
import queue
import signal
import psutil
import threading
import subprocess
from typing import Dict, Any, List, Optional, Set

# ─────────────────────────────────────────────────────────────────────────────
# Thread-Safe Global State Dictionaries (ဗဟိုပြု Memory သိုလှောင်မှုများ)
# ─────────────────────────────────────────────────────────────────────────────
# jobs: Stores metadata, phase, status, timestamps, and output file references
jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()

# active_processes: Direct references to spawned subprocess.Popen objects
active_processes: Dict[str, subprocess.Popen] = {}

# active_process_pids: Operating system process identifiers for recursive tree kills
active_process_pids: Dict[str, Set[int]] = {}

# SSE real-time log distribution queues per job ID
_log_subscribers: Dict[str, List[queue.Queue]] = {}
_subscribers_lock = threading.Lock()

# Job retention policy: Retain finished/cancelled jobs in memory for 2 hours (7200 seconds)
JOB_RETENTION_SECONDS: int = 7200


# ─────────────────────────────────────────────────────────────────────────────
# Job Lifecycle Management Functions (အလုပ် အဆင့်ဆင့် စီမံခန့်ခွဲခြင်း)
# ─────────────────────────────────────────────────────────────────────────────
def create_job(
    job_id: str,
    source: str,
    phase: str = "Starting...",
    status: str = "running",
    language: str = "burmese",
    tts_engine: str = "edge_tts",
    engine_mode: str = "recap",
) -> Dict[str, Any]:
    """
    Initializes and registers a new job entry into memory.
    အလုပ်သစ်တစ်ခုအား memory စာရင်းတွင် စတင်ဖန်တီး မှတ်ပုံတင်ပေးသည်။
    """
    entry = {
        "job_id": job_id,
        "name": str(source),
        "source": str(source),
        "status": status,
        "phase": phase,
        "created_at": time.time(),
        "language": str(language),
        "tts_engine": str(tts_engine),
        "engine_mode": str(engine_mode),
        "buffer": None,
        "elapsed_sec": 0,
    }
    with jobs_lock:
        jobs[job_id] = entry
    return entry


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a thread-safe copy of a job's current state.
    Job ID အလိုက် လက်ရှိ အခြေအနေကို ထုတ်ယူပေးသည်။
    """
    with jobs_lock:
        job = jobs.get(job_id)
        return dict(job) if job else None


def get_all_jobs() -> Dict[str, Dict[str, Any]]:
    """
    Returns a snapshot of all tracked jobs.
    လက်ရှိ အလုပ်အားလုံး၏ snapshot စာရင်းကို ထုတ်ပေးသည်။
    """
    with jobs_lock:
        return {k: dict(v) for k, v in jobs.items()}


def has_running_job() -> bool:
    """
    Checks if there is currently any job executing with status == 'running'.
    လက်ရှိတွင် 'running' ဖြစ်နေသော အလုပ် ရှိ/မရှိ စစ်ဆေးပေးသည်။
    """
    with jobs_lock:
        return any(j.get("status") == "running" for j in jobs.values())


def update_job_phase(job_id: str, phase: str, status: Optional[str] = None):
    """
    Updates the execution phase and optional status of an active job.
    အလုပ်၏ လက်ရှိလုပ်ဆောင်နေသော Phase နှင့် Status ကို update ပြုလုပ်ပေးသည်။
    """
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["phase"] = phase
            if status:
                jobs[job_id]["status"] = status


def cleanup_old_jobs(retention_seconds: int = JOB_RETENTION_SECONDS):
    """
    Purges completed, failed, or cancelled jobs older than retention_seconds.
    သတ်မှတ်ထားသော အချိန်ထက် ကျော်လွန်နေသည့် အဟောင်းများကို ရှင်းလင်းပေးသည်။
    """
    now = time.time()
    with jobs_lock:
        to_delete = []
        for jid, job in list(jobs.items()):
            status = job.get("status")
            created = job.get("created_at", 0)
            # Purge finished, errored, or cancelled jobs exceeding the retention window
            if status in ("done", "error", "cancelled") and (now - created > retention_seconds):
                to_delete.append(jid)
        for jid in to_delete:
            jobs.pop(jid, None)
            active_processes.pop(jid, None)
            active_process_pids.pop(jid, None)


# ─────────────────────────────────────────────────────────────────────────────
# OS Process Registration & Termination (Operating System Process စီမံမှု)
# ─────────────────────────────────────────────────────────────────────────────
def register_active_process(job_id: str, proc: subprocess.Popen):
    """
    Registers a running OS child process (e.g. FFmpeg, Demucs, Whisper).
    လည်ပတ်နေသော OS Process အား Job ID နှင့် ချိတ်ဆက် မှတ်ပုံတင်သည်။
    """
    with jobs_lock:
        active_processes[job_id] = proc
        if job_id not in active_process_pids:
            active_process_pids[job_id] = set()
        if proc and hasattr(proc, "pid") and proc.pid:
            active_process_pids[job_id].add(proc.pid)


def unregister_active_process(job_id: str):
    """
    Unregisters a completed OS process.
    ပြီးဆုံးသွားသော Process အား စာရင်းမှ ဖယ်ရှားသည်။
    """
    with jobs_lock:
        active_processes.pop(job_id, None)
        active_process_pids.pop(job_id, None)


def force_stop_active_jobs(target_job_id: Optional[str] = None) -> int:
    """
    Forcefully terminates all active child processes for a job (or all jobs).
    Recursively kills entire process trees on Windows and Linux.
    
    အလုပ်တစ်ခု (သို့မဟုတ် အားလုံး) ၏ Process များအားလုံးကို အမြစ်ပြတ် ရပ်တန့်ပစ်သည်။
    """
    stopped_count = 0
    with jobs_lock:
        target_pids: Set[int] = set()

        if target_job_id:
            pids = active_process_pids.get(target_job_id, set())
            target_pids.update(pids)
            if target_job_id in jobs:
                jobs[target_job_id]["status"] = "cancelled"
                jobs[target_job_id]["phase"] = "Stopped by user"
        else:
            for jid, job in jobs.items():
                if job.get("status") == "running":
                    job["status"] = "cancelled"
                    job["phase"] = "Stopped by user"
            for pids in active_process_pids.values():
                target_pids.update(pids)

    # Terminate process trees using psutil
    for pid in target_pids:
        try:
            if not psutil.pid_exists(pid):
                continue
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()
            stopped_count += 1
        except Exception as e:
            print(f"[WARN] Process termination notice for PID {pid}: {e}")

    # Fallback kill via subprocess on Windows
    if sys.platform == "win32" and target_pids:
        for pid in target_pids:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                pass

    return stopped_count


# ─────────────────────────────────────────────────────────────────────────────
# Realtime SSE Log Streaming Distribution (အချိန်နှင့်တပြေးညီ Log ဖြန့်ဝေခြင်း)
# ─────────────────────────────────────────────────────────────────────────────
def subscribe_logs(job_id: str) -> queue.Queue:
    """
    Creates a new subscriber queue to receive live streaming logs for a job.
    Job တစ်ခု၏ Log များကို နားထောင်မည့် SSE Queue အသစ်တစ်ခု ဖန်တီးပေးသည်။
    """
    q: queue.Queue = queue.Queue(maxsize=1000)
    with _subscribers_lock:
        if job_id not in _log_subscribers:
            _log_subscribers[job_id] = []
        _log_subscribers[job_id].append(q)
    return q


def unsubscribe_logs(job_id: str, q: queue.Queue):
    """
    Removes a subscriber queue when an SSE client disconnects.
    Client ချိတ်ဆက်မှု ပြတ်တောက်သွားပါက Queue ကို ဖယ်ရှားပေးသည်။
    """
    with _subscribers_lock:
        if job_id in _log_subscribers:
            try:
                _log_subscribers[job_id].remove(q)
                if not _log_subscribers[job_id]:
                    _log_subscribers.pop(job_id, None)
            except ValueError:
                pass


def publish_log(job_id: str, message: Dict[str, Any]):
    """
    Broadcasts a log message to all active SSE subscribers for a job.
    လက်ရှိ နားထောင်နေကြသော Subscriber အားလုံးဆီသို့ Log စာသား ဖြန့်ဝေပေးသည်။
    """
    with _subscribers_lock:
        subscribers = _log_subscribers.get(job_id, [])
        for q in list(subscribers):
            try:
                q.put_nowait(message)
            except queue.Full:
                pass
