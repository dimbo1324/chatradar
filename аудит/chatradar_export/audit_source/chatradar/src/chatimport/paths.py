"""Where things live: application folders and the chat-data root (priority per spec §7.3)."""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from platformdirs import user_data_dir, user_desktop_dir

APP_NAME = "ChatImport"
ROOT_ENV = "CHATIMPORT_ROOT"
PRIVATE_DIR_MODE: Final = 0o700
CLOUD_ENV_VARS: Final = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
_CLOUD_FOLDER_MARKER: Final = "onedrive"


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
        """Create the folders; on POSIX the base and the session folder are owner-only,
        because the session file is full access to the account."""
        for folder in (self.base, self.session_file.parent, self.log_dir, self.control_dir):
            folder.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            for folder in (self.base, self.session_file.parent):
                with contextlib.suppress(OSError):
                    folder.chmod(PRIVATE_DIR_MODE)


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


def is_cloud_synced(path: Path, env: dict[str, str] | None = None) -> bool:
    """True for a folder under OneDrive: a path component that names it (Known Folder Move
    puts the Desktop at `.../OneDrive/Desktop`), or a folder below its environment variables."""
    environment = os.environ if env is None else env
    target = path.absolute()
    if any(_CLOUD_FOLDER_MARKER in part.casefold() for part in target.parts):
        return True
    for name in CLOUD_ENV_VARS:
        value = environment.get(name)
        if value and target.is_relative_to(Path(value).absolute()):
            return True
    return False


def cloud_sync_warning(path: Path, env: dict[str, str] | None = None) -> str | None:
    """A one-line warning when the data folder is synced to the cloud, else None."""
    if not is_cloud_synced(path, env):
        return None
    return (
        f"the data folder {path} is synced to the cloud; the archive holds sender names, "
        "so move it with `chatimport set-root`"
    )
