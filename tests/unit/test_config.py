from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.config import Environment, Settings

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_defaults_point_to_sqlite_in_data_dir(isolated_env: Path) -> None:
    settings = Settings()

    assert settings.env is Environment.DEV
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert settings.database_url.endswith("data/chatradar.db")
    assert not settings.telegram.is_configured


def test_nested_env_and_explicit_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATRADAR_DATABASE_URL", "postgresql+asyncpg://u:p@db/chatradar")
    monkeypatch.setenv("CHATRADAR_TELEGRAM__API_ID", "12345")
    monkeypatch.setenv("CHATRADAR_TELEGRAM__API_HASH", "deadbeef")
    monkeypatch.setenv("CHATRADAR_WORKER__RECHECK_DAYS", "3")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@db/chatradar"
    assert settings.telegram.is_configured
    assert settings.telegram.api_id == 12345
    assert settings.worker.recheck_days == 3


def test_empty_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATRADAR_TELEGRAM__API_ID", "")
    monkeypatch.setenv("CHATRADAR_DATABASE_URL", "")

    settings = Settings()

    assert settings.telegram.api_id is None
    assert settings.database_url.startswith("sqlite")


def test_secret_is_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATRADAR_TELEGRAM__API_HASH", "super-secret-hash")

    assert "super-secret-hash" not in repr(Settings())


def test_ensure_dirs_creates_layout(isolated_env: Path) -> None:
    settings = Settings()
    settings.ensure_dirs()

    assert settings.raw_dir.is_dir()
    assert settings.sessions_dir.is_dir()
