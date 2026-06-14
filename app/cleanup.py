import shutil
import threading
import time
from pathlib import Path

from .config import Settings, settings
from .pipeline import read_json


def start_cleanup_worker(cfg: Settings = settings) -> None:
    if cfg.cleanup_interval_minutes <= 0:
        return

    thread = threading.Thread(target=cleanup_loop, args=(cfg,), daemon=True)
    thread.start()


def cleanup_loop(cfg: Settings) -> None:
    cleanup_once(cfg)
    interval = max(60, cfg.cleanup_interval_minutes * 60)
    while True:
        time.sleep(interval)
        cleanup_once(cfg)


def cleanup_once(cfg: Settings = settings) -> dict[str, int]:
    now = int(time.time())
    removed_jobs = cleanup_jobs(now, cfg)
    removed_logs = cleanup_logs(now, cfg)
    return {"removed_jobs": removed_jobs, "removed_logs": removed_logs}


def cleanup_jobs(now: int, cfg: Settings) -> int:
    jobs_root = cfg.data_dir / "jobs" / "by-user"
    if not jobs_root.exists() or cfg.job_retention_days <= 0:
        return 0

    cutoff = now - cfg.job_retention_days * 24 * 60 * 60
    removed = 0
    for job_dir in jobs_root.glob("*/*"):
        if not job_dir.is_dir():
            continue
        if job_timestamp(job_dir) >= cutoff:
            continue
        shutil.rmtree(job_dir, ignore_errors=True)
        removed += 1
    return removed


def cleanup_logs(now: int, cfg: Settings) -> int:
    logs_root = cfg.data_dir / "logs"
    if not logs_root.exists() or cfg.log_retention_days <= 0:
        return 0

    cutoff = now - cfg.log_retention_days * 24 * 60 * 60
    removed = 0
    for path in logs_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            mtime = int(path.stat().st_mtime)
        except FileNotFoundError:
            continue
        if mtime >= cutoff:
            continue
        path.unlink(missing_ok=True)
        removed += 1

    prune_empty_dirs(logs_root)
    return removed


def job_timestamp(job_dir: Path) -> int:
    meta_path = job_dir / "meta.json"
    try:
        metadata = read_json(meta_path)
        return int(metadata.get("updated_at") or metadata.get("created_at") or job_dir.stat().st_mtime)
    except Exception:
        return int(job_dir.stat().st_mtime)


def prune_empty_dirs(root: Path) -> None:
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass
