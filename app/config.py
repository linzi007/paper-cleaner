import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("PAPER_CLEANER_DATA_DIR", "./data"))
    tencent_secret_id: str | None = os.getenv("TENCENTCLOUD_SECRET_ID")
    tencent_secret_key: str | None = os.getenv("TENCENTCLOUD_SECRET_KEY")
    tencent_region: str = os.getenv("TENCENTCLOUD_REGION", "ap-guangzhou")
    tencent_use_new_model: bool = _bool_env("PAPER_CLEANER_TENCENT_USE_NEW_MODEL", True)
    render_dpi: int = int(os.getenv("PAPER_CLEANER_RENDER_DPI", "180"))
    max_pages: int = int(os.getenv("PAPER_CLEANER_MAX_PAGES", "20"))
    job_retention_days: int = int(os.getenv("PAPER_CLEANER_JOB_RETENTION_DAYS", "7"))
    log_retention_days: int = int(os.getenv("PAPER_CLEANER_LOG_RETENTION_DAYS", "7"))
    cleanup_interval_minutes: int = int(os.getenv("PAPER_CLEANER_CLEANUP_INTERVAL_MINUTES", "360"))
    default_admin_phone: str = os.getenv("PAPER_CLEANER_DEFAULT_ADMIN_PHONE", "13800000000")


settings = Settings()
