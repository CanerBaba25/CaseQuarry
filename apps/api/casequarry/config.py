from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CASEQUARRY_", env_file=".env", extra="ignore", populate_by_name=True)

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(default="postgresql+psycopg://casequarry@127.0.0.1:5432/casequarry", repr=False)
    storage_path: Path = Field(default=Path(".data"), validation_alias=AliasChoices("CASEQUARRY_STORAGE_ROOT", "CASEQUARRY_STORAGE_PATH", "storage_path"))
    setup_token: str | None = Field(default=None, repr=False)
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
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_timeout_seconds: int = Field(default=60, ge=5, le=300)
    ocr_max_pages: int = Field(default=200, ge=1, le=2000)
    ocr_max_pixels: int = Field(default=25_000_000, ge=1_000_000, le=100_000_000)
    ocr_dpi: int = Field(default=200, ge=72, le=400)
    extraction_timeout_seconds: int = Field(default=180, ge=15, le=900)
    worker_import_records_per_tick: int = Field(default=25, ge=1, le=200)
    tesseract_command: str | None = None
    ai_enabled: bool = False
    ai_local_base_url: str = "http://127.0.0.1:11434"
    ai_model: str = ""
    allow_remote_ai: bool = True
    provider_key_encryption_key: str | None = Field(default=None, repr=False)
    export_signing_key_file: Path | None = Field(default=None, repr=False)
    antivirus_command: str | None = None

    @field_validator("export_signing_key_file", mode="before")
    @classmethod
    def optional_signing_key_file(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production" or not self.allow_insecure_local_cookies
