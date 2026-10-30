"""Application configuration (environment driven, prefix ``QHC_``)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GB = 1024**3
MB = 1024**2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="QHC_", extra="ignore")

    app_name: str = "QRadar Health Checkup Platform"
    environment: str = "development"  # development | production

    # --- persistence ---------------------------------------------------
    database_url: str = "sqlite:///./data/qhc.db"
    storage_dir: Path = Path("./data/storage")

    # --- security ------------------------------------------------------
    secret_key: str = "dev-only-change-me-dev-only-change-me"
    access_token_minutes: int = 480
    admin_email: str | None = None
    admin_password: str | None = None
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    # --- background processing ----------------------------------------
    run_mode: str = "inline"  # inline (thread pool) | celery
    redis_url: str = "redis://localhost:6379/0"
    inline_workers: int = 4
    parse_workers: int = 4
    stale_job_seconds: int = 300

    # --- upload / archive safety limits -------------------------------
    max_upload_bytes: int = 100 * GB
    upload_chunk_bytes: int = 16 * MB
    max_archive_files: int = 5_000_000
    max_extracted_member_bytes: int = 20 * GB   # per extracted member (dumps can be large)
    max_text_member_bytes: int = 256 * MB       # per generic text member
    max_total_extracted_bytes: int = 200 * GB
    max_compression_ratio: float = 1000.0
    ratio_check_threshold_bytes: int = 2 * GB
    max_nested_depth: int = 4
    max_path_length: int = 1024

    # --- parsing limits -------------------------------------------------
    max_rows_per_table: int = 2_000_000

    # --- optional LLM augmentation for the assistant ---------------------
    llm_base_url: str | None = None   # OpenAI compatible, e.g. https://host/v1
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    # --- node (pptxgenjs) ------------------------------------------------
    node_bin: str = "node"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def assessments_dir(self) -> Path:
        return self.storage_dir / "assessments"

    @property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    @property
    def logos_dir(self) -> Path:
        return self.storage_dir / "logos"

    def ensure_dirs(self) -> None:
        for d in (self.storage_dir, self.uploads_dir, self.assessments_dir, self.exports_dir, self.logos_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
