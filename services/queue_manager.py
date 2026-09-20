"""
Queue Manager & Sequential FIFO Worker (တန်းစီစနစ်နှင့် နောက်ကွယ် အလုပ်သမား)
==========================================================================
Manages sequential execution of video production jobs. When a pipeline is
already active, new requests are queued in FIFO order and executed one after another.

ဤ module သည် ဗီဒီယို ထုတ်လုပ်မှု အလုပ်များကို တစ်ခုပြီးမှ တစ်ခု အစဉ်လိုက်
အလိုအလျောက် ဆက်လက် လုပ်ဆောင်ပေးသည့် Background FIFO Queue စနစ် ဖြစ်ပါသည်။
"""

import time
import threading
from typing import List, Dict, Any, Optional
from services.job_manager import has_running_job, jobs, jobs_lock

# ─────────────────────────────────────────────────────────────────────────────
# Queue Data Structure & Synchronization Lock (တန်းစီစာရင်းနှင့် Lock)
# ─────────────────────────────────────────────────────────────────────────────
job_queue: List[Dict[str, Any]] = []
queue_lock = threading.Lock()
_worker_started = False
_worker_thread: Optional[threading.Thread] = None


def enqueue_job(job_entry: Dict[str, Any]) -> int:
    """
    Appends a new job entry to the sequential queue.
    Returns its 1-based position in line.
    
    အလုပ်သစ်တစ်ခုအား တန်းစီစာရင်းထဲသို့ ထည့်သွင်းပေးပြီး ရောက်ရှိသည့် အလှည့်နံပါတ်ကို ပြန်ပေးသည်။
    """
    with queue_lock:
        job_queue.append(job_entry)
        position = len(job_queue)

    jid = job_entry.get("job_id")
    if jid:
        with jobs_lock:
            if jid in jobs:
                jobs[jid]["status"] = "queued"
                jobs[jid]["phase"] = f"Queued (#{position} in line)"

    print(f"[*] Queue: Enqueued job {jid} at position #{position}")
    return position


def remove_from_queue(job_id: str) -> bool:
    """
    Removes a specific job from the waiting queue by its job ID.
    Job ID အလိုက် တန်းစီစာရင်းထဲမှ ဖယ်ထုတ်ပယ်ဖျက်သည်။
    """
    with queue_lock:
        original_len = len(job_queue)
        job_queue[:] = [item for item in job_queue if item.get("job_id") != job_id]
        removed = len(job_queue) < original_len

    if removed:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "cancelled"
                jobs[job_id]["phase"] = "Removed from queue"
        print(f"[*] Queue: Removed job {job_id} from queue.")
    return removed


def get_queue_items() -> List[Dict[str, Any]]:
    """
    Returns a thread-safe list copy of currently queued jobs.
    လက်ရှိ တန်းစီနေသော အလုပ်များစာရင်းကို ကူးယူထုတ်ပေးသည်။
    """
    with queue_lock:
        return [
            {
                "job_id": item.get("job_id"),
                "name": item.get("name"),
                "source": item.get("source"),
                "language": item.get("language"),
                "tts_engine": item.get("tts_engine"),
                "engine_mode": item.get("engine_mode"),
                "created_at": item.get("created_at"),
            }
            for item in job_queue
        ]


def _queue_worker_loop():
    """
    Continuous background loop that monitors job completion and starts next queued item.
    နောက်ကွယ်တွင် အမြဲ စောင့်ကြည့်နေပြီး လက်ရှိအလုပ် ပြီးသည်နှင့် နောက်တစ်ခုကို ချက်ချင်း စတင်ပေးသည်။
    """
    while True:
        try:
            time.sleep(2.0)
            if has_running_job():
                continue

            next_job = None
            with queue_lock:
                if job_queue:
                    next_job = job_queue.pop(0)

            if next_job:
                jid = next_job.get("job_id")
                target = next_job.get("target")
                args = next_job.get("args", ())

                print(f"\n[*] Queue Worker: Automatically starting next queued job {jid}...")
                with jobs_lock:
                    if jid in jobs:
                        jobs[jid]["status"] = "running"
                        jobs[jid]["phase"] = "Starting from queue..."

                t = threading.Thread(target=target, args=args, daemon=True)
                t.start()
        except Exception as e:
            print(f"[WARN] Queue Worker exception: {e}")
            time.sleep(3.0)


def start_queue_worker():
    """
    Starts the background sequential queue worker daemon thread if not already active.
    Queue စီမံပေးမည့် Background Worker Thread ကို စတင်လည်ပတ်စေသည်။
    """
    global _worker_started, _worker_thread
    if not _worker_started:
        _worker_started = True
        _worker_thread = threading.Thread(target=_queue_worker_loop, daemon=True, name="JobQueueWorkerDaemon")
        _worker_thread.start()
        print("[*] Queue Manager: Background sequential queue worker daemon started.")
