import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from brain.memory import MovieState


def get_db_path(output_dir: str = "outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, "movie_metadata.db")


def ensure_db(output_dir: str = "outputs") -> str:
    """Ensures database exists and all tables are initialized with WAL mode."""
    db_path = get_db_path(output_dir)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        
        # 1. Movie State Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movie_state (
                project_dir TEXT PRIMARY KEY,
                movie_name TEXT,
                movie_path TEXT,
                language TEXT,
                whisper_model TEXT,
                progress INTEGER,
                current_phase TEXT,
                updated_at TEXT,
                state_json TEXT
            )
            """
        )
        
        # 2. Jobs Table (Database-backed job queue for Web UI)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                input_source TEXT,
                status TEXT DEFAULT 'running',
                phase TEXT DEFAULT 'Starting...',
                created_at REAL,
                updated_at TEXT
            )
            """
        )
        
        # 3. API Key Usage Table (Unified quota tracker)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_key_usage (
                masked_key TEXT,
                model_name TEXT,
                used_today INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                utc_date TEXT,
                last_updated_utc TEXT,
                PRIMARY KEY (masked_key, model_name)
            )
            """
        )
        # Indexes for fast lookup
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);")
        conn.commit()
    finally:
        conn.close()
    return db_path


# ─────────────────────────────────────────────────────────────────────────────
# MOVIE STATE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def save_movie_state(state: MovieState, output_dir: str = "outputs") -> None:
    db_path = ensure_db(output_dir)
    state_json = state.model_dump_json(indent=4)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO movie_state (
                project_dir,
                movie_name,
                movie_path,
                language,
                whisper_model,
                progress,
                current_phase,
                updated_at,
                state_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.project_dir,
                state.movie_name,
                state.movie_path,
                getattr(state, 'language', None) or None,
                getattr(state, 'whisper_model', None) or None,
                int(state.progress or 0),
                state.current_phase or "",
                now,
                state_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_custom_movie_state(
    project_dir: str,
    movie_name: str,
    movie_path: str = "",
    language: str = "burmese",
    whisper_model: str = "gemini",
    progress: int = 100,
    current_phase: str = "Done",
    state_dict: Optional[dict] = None,
    output_dir: str = "outputs"
) -> None:
    """Saves custom project state (e.g. HardsubEngine or SubtitleEngine) to SQLite movie_state table."""
    db_path = ensure_db(output_dir)
    state_json = json.dumps(state_dict or {}, ensure_ascii=False, indent=2)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO movie_state (
                project_dir,
                movie_name,
                movie_path,
                language,
                whisper_model,
                progress,
                current_phase,
                updated_at,
                state_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_dir,
                movie_name,
                movie_path,
                language,
                whisper_model,
                int(progress or 0),
                current_phase or "",
                now,
                state_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_movie_state(project_dir: str, output_dir: str = "outputs") -> Optional[dict]:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return None

    norm_slash = str(project_dir).replace("/", "\\")
    norm_fwd = str(project_dir).replace("\\", "/")

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT project_dir, movie_name, movie_path, language, whisper_model, progress, current_phase, updated_at, state_json "
            "FROM movie_state WHERE project_dir = ? OR project_dir = ? OR project_dir = ?",
            (project_dir, norm_slash, norm_fwd)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "project_dir": row[0],
            "movie_name": row[1],
            "movie_path": row[2],
            "language": row[3],
            "whisper_model": row[4],
            "progress": row[5],
            "current_phase": row[6],
            "updated_at": row[7],
            "state_json": json.loads(row[8]) if row[8] else None,
        }
    finally:
        conn.close()

get_movie_state = load_movie_state


def delete_movie_state(project_dir: str, output_dir: str = "outputs") -> None:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return

    norm_slash = str(project_dir).replace("/", "\\")
    norm_fwd = str(project_dir).replace("\\", "/")

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute("DELETE FROM movie_state WHERE project_dir = ? OR project_dir = ? OR project_dir = ?", (project_dir, norm_slash, norm_fwd))
        conn.commit()
    finally:
        conn.close()


def list_movie_states(output_dir: str = "outputs") -> list[dict]:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT project_dir, movie_name, language, whisper_model, progress, current_phase, updated_at FROM movie_state ORDER BY updated_at DESC"
        )
        return [
            {
                "project_dir": row[0],
                "movie_name": row[1],
                "language": row[2],
                "whisper_model": row[3],
                "progress": row[4],
                "current_phase": row[5],
                "updated_at": row[6],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# JOB QUEUE OPERATIONS (Persistent Web UI State)
# ─────────────────────────────────────────────────────────────────────────────

def create_job(job_id: str, input_source: str, phase: str = "Starting...", output_dir: str = "outputs") -> None:
    db_path = ensure_db(output_dir)
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (job_id, input_source, status, phase, created_at, updated_at)
            VALUES (?, ?, 'running', ?, ?, ?)
            """,
            (job_id, input_source, phase, now_ts, now_iso)
        )
        conn.commit()
    finally:
        conn.close()


def update_job(job_id: str, status: Optional[str] = None, phase: Optional[str] = None, output_dir: str = "outputs") -> None:
    db_path = ensure_db(output_dir)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        if status and phase:
            conn.execute("UPDATE jobs SET status = ?, phase = ?, updated_at = ? WHERE job_id = ?", (status, phase, now_iso, job_id))
        elif status:
            conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?", (status, now_iso, job_id))
        elif phase:
            conn.execute("UPDATE jobs SET phase = ?, updated_at = ? WHERE job_id = ?", (phase, now_iso, job_id))
        conn.commit()
    finally:
        conn.close()


def clean_stale_running_jobs(output_dir: str = "outputs") -> int:
    """Marks any lingering 'running' jobs from prior interrupted server runs as 'interrupted'."""
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return 0
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cur = conn.execute(
            "UPDATE jobs SET status = 'interrupted', phase = 'Server interrupted / restarted', updated_at = ? WHERE status = 'running'",
            (now_iso,)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_active_job(output_dir: str = "outputs") -> Optional[dict]:
    """Returns the most recent currently running job, if any."""
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT job_id, input_source, status, phase, created_at, updated_at FROM jobs WHERE status = 'running' ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "job_id": row[0],
            "input_source": row[1],
            "status": row[2],
            "phase": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
    finally:
        conn.close()


def get_job(job_id: str, output_dir: str = "outputs") -> Optional[dict]:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT job_id, input_source, status, phase, created_at, updated_at FROM jobs WHERE job_id = ?",
            (job_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "job_id": row[0],
            "input_source": row[1],
            "status": row[2],
            "phase": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED API KEY USAGE OPERATIONS (SQLite Quota Tracker)
# ─────────────────────────────────────────────────────────────────────────────

def reserve_sqlite_model_usage(masked_key: str, model_name: str, limit: int, utc_date: str, output_dir: str = "outputs") -> bool:
    """Atomically checks limit and reserves 1 usage if under limit in SQLite."""
    db_path = ensure_db(output_dir)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT used_today, utc_date FROM api_key_usage WHERE masked_key = ? AND model_name = ?",
            (masked_key, model_name)
        )
        row = cursor.fetchone()
        
        used = 0
        if row:
            rec_used, rec_utc = row[0], row[1]
            if rec_utc == utc_date:
                used = rec_used
            else:
                used = 0  # Date rolled over, reset to 0

        if used >= limit:
            return False

        # Atomically increment
        new_used = used + 1
        conn.execute(
            """
            INSERT OR REPLACE INTO api_key_usage (masked_key, model_name, used_today, status, utc_date, last_updated_utc)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (masked_key, model_name, new_used, utc_date, now_iso)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def record_sqlite_model_usage(masked_key: str, model_name: str, status: str, utc_date: str, output_dir: str = "outputs") -> None:
    """Records completion status. If error/rate-limited, refunds the reserved usage."""
    db_path = ensure_db(output_dir)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT used_today FROM api_key_usage WHERE masked_key = ? AND model_name = ?",
            (masked_key, model_name)
        )
        row = cursor.fetchone()
        used = row[0] if row else 0

        if status != "success" and used > 0:
            used -= 1  # Refund failure

        status_text = "active" if status == "success" else ("rate-limited (RPM)" if status == "rate_limited" else status)

        conn.execute(
            """
            INSERT OR REPLACE INTO api_key_usage (masked_key, model_name, used_today, status, utc_date, last_updated_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (masked_key, model_name, used, status_text, utc_date, now_iso)
        )
        conn.commit()
    finally:
        conn.close()


def load_sqlite_usage_db(utc_date: str, output_dir: str = "outputs") -> dict:
    """Returns usage dictionary structured identically to legacy tracker for seamless compatibility."""
    db_path = ensure_db(output_dir)
    data = {"utc_date": utc_date, "keys": {}}

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT masked_key, model_name, used_today, status, utc_date, last_updated_utc FROM api_key_usage"
        )
        for row in cursor.fetchall():
            m_key, m_name, used, stat, rec_utc, last_up = row[0], row[1], row[2], row[3], row[4], row[5]
            if rec_utc != utc_date:
                used = 0
                stat = "active"

            if m_key not in data["keys"]:
                data["keys"][m_key] = {
                    "masked_key": m_key,
                    "utc_date": utc_date,
                    "last_updated_utc": last_up,
                    "models": {}
                }
            data["keys"][m_key]["models"][m_name] = {
                "used_today": used,
                "status": stat
            }
        return data
    finally:
        conn.close()
