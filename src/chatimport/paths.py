"""Where things live: application folders and the chat-data root (priority per spec §7.3)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir, user_desktop_dir

APP_NAME = "ChatImport"
ROOT_ENV = "CHATIMPORT_ROOT"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Folders that must survive deleting the `ChatImport` data folder."""

    base: Path

    @property
    def config_file(self) -> Path:
        return self.base / "config.toml"

    @property
    def default_library_file(self) -> Path:
        return self.base / "chats.toml"

    @property
    def session_file(self) -> Path:
        return self.base / "session" / "chatimport.session"

    @property
    def log_dir(self) -> Path:
        return self.base / "logs"

    @property
    def lock_file(self) -> Path:
        return self.base / "chatimport.lock"

    @property
    def control_dir(self) -> Path:
        return self.base / "control"

    def ensure(self) -> None:
        for folder in (self.base, self.session_file.parent, self.log_dir, self.control_dir):
            folder.mkdir(parents=True, exist_ok=True)


def app_paths(base: Path | None = None) -> AppPaths:
    return AppPaths(base or Path(user_data_dir(APP_NAME, appauthor=False, roaming=False)))


def normalize_root(value: str) -> Path:
    """Expand `~` and environment variables; add `ChatImport` unless the path ends with it."""
    path = Path(os.path.expandvars(value)).expanduser()
    return path if path.name.lower() == APP_NAME.lower() else path / APP_NAME


def resolve_root(
    cli_root: str | None = None,
    config_root: str = "",
    env: dict[str, str] | None = None,
) -> Path:
    """First set source wins: `--root`, `CHATIMPORT_ROOT`, `output.root_dir`, the Desktop."""
    environment = os.environ if env is None else env
    for candidate in (cli_root, environment.get(ROOT_ENV), config_root):
        if candidate:
            return normalize_root(candidate)
    return Path(user_desktop_dir()) / APP_NAME


def library_path(configured: str, paths: AppPaths) -> Path:
    return (
        Path(os.path.expandvars(configured)).expanduser()
        if configured
        else (paths.default_library_file)
    )
