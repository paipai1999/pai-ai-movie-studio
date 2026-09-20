"""
Services & Background Job Management Package (နောက်ကွယ် အလုပ်များနှင့် စနစ်ဝန်ဆောင်မှုများ)
========================================================================================
This package manages background pipeline execution, thread-safe job tracking,
process termination, SSE realtime log distribution, and FIFO queue processing.

ဤ package သည် နောက်ကွယ်တွင် လည်ပတ်နေသော video rendering အလုပ်များ၊
Thread Lock များ၊ လုပ်ငန်းစဉ် ချက်ချင်း ရပ်တန့်နိုင်မှု၊ SSE live log ထုတ်လွှင့်မှုနှင့်
FIFO Queue စနစ်တို့ကို စနစ်တကျ စီမံခန့်ခွဲပေးပါသည်။
"""

from services.job_manager import (
    jobs,
    jobs_lock,
    active_processes,
    active_process_pids,
    JOB_RETENTION_SECONDS,
    create_job,
    get_job,
    get_all_jobs,
    has_running_job,
    update_job_phase,
    cleanup_old_jobs,
    register_active_process,
    unregister_active_process,
    force_stop_active_jobs,
    subscribe_logs,
    unsubscribe_logs,
    publish_log,
)
from services.queue_manager import (
    job_queue,
    queue_lock,
    enqueue_job,
    remove_from_queue,
    get_queue_items,
    start_queue_worker,
)

__all__ = [
    "jobs",
    "jobs_lock",
    "active_processes",
    "active_process_pids",
    "JOB_RETENTION_SECONDS",
    "create_job",
    "get_job",
    "get_all_jobs",
    "has_running_job",
    "update_job_phase",
    "cleanup_old_jobs",
    "register_active_process",
    "unregister_active_process",
    "force_stop_active_jobs",
    "subscribe_logs",
    "unsubscribe_logs",
    "publish_log",
    "job_queue",
    "queue_lock",
    "enqueue_job",
    "remove_from_queue",
    "get_queue_items",
    "start_queue_worker",
]
