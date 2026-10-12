from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CASEQUARRY_", env_file=".env", extra="ignore", populate_by_name=True)

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///.data/casequarry.db"
    storage_path: Path = Field(default=Path(".data"), validation_alias=AliasChoices("CASEQUARRY_STORAGE_ROOT", "CASEQUARRY_STORAGE_PATH", "storage_path"))
    setup_token: str | None = None
    setup_token_ttl_seconds: int = 3600
    session_ttl_seconds: int = 28800
    worker_mode: Literal["embedded", "external", "disabled"] = "embedded"
    worker_poll_seconds: float = 0.25
    allow_insecure_local_cookies: bool = True
    max_upload_bytes: int = 256 * 1024 * 1024
    max_batch_files: int = 200
    max_archive_entries: int = 2000
    max_archive_expanded_bytes: int = 512 * 1024 * 1024
    max_archive_expansion_ratio: int = 100
    max_archive_depth: int = 3
    max_extracted_chars: int = 4_000_000
    max_case_bytes: int = 20 * 1024 * 1024 * 1024
    ai_enabled: bool = False
    ai_local_base_url: str = "http://127.0.0.1:11434"
    ai_model: str = ""
    allow_remote_ai: bool = False
    antivirus_command: str | None = None

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production" or not self.allow_insecure_local_cookies
