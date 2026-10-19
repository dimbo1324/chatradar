"""Конфигурация приложения. Единственный источник настроек — переменные окружения и `.env`."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    PROD = "prod"


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class TelegramSettings(BaseModel):
    api_id: int | None = None
    api_hash: SecretStr | None = None
    session_name: str = "collector"
    flood_sleep_threshold: int = Field(default=120, ge=0)

    @property
    def is_configured(self) -> bool:
        return self.api_id is not None and self.api_hash is not None


class WorkerSettings(BaseModel):
    sync_interval_hours: float = Field(default=4, gt=0)
    recheck_days: int = Field(default=7, ge=0)
    pause_between_chats_sec: float = Field(default=3, ge=0)
    batch_size: int = Field(default=500, gt=0)


class WebSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHATRADAR_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # «CHATRADAR_TELEGRAM__API_ID=» в .env = значение по умолчанию
        extra="ignore",
    )

    env: Environment = Environment.DEV
    log_level: LogLevel = "INFO"
    data_dir: Path = Path("data")
    # Пусто → SQLite в data_dir. Смена БД = смена этой строки.
    database_url: str = ""

    telegram: TelegramSettings = TelegramSettings()
    worker: WorkerSettings = WorkerSettings()
    web: WebSettings = WebSettings()

    @model_validator(mode="after")
    def _default_database_url(self) -> Self:
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{(self.data_dir / 'chatradar.db').as_posix()}"
        return self

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.sessions_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
