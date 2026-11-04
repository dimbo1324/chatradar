"""Changing the output folder (spec §7.3): validation and moving the data."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import shutil
import uuid
from typing import TYPE_CHECKING, Final

from chatimport.paths import is_cloud_synced
from chatimport.ports import ChatImportError
from chatimport.storage.fileio import walk_files
from chatimport.storage.layout import STATE_FILE, iter_chat_folders

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

STATUS_FILE: Final = "_status.json"


def _looks_like_data_root(folder: Path) -> bool:
    return (folder / STATUS_FILE).exists() or any(
        (chat / STATE_FILE).exists() for chat in iter_chat_folders(folder)
    )


def validate_new_root(
    new: Path, old: Path, *, app_base: Path | None = None, move: bool = True
) -> list[str]:
    """Raise when `new` cannot be used; return warnings for a usable one.

    `app_base` (the folder with the session and config) must neither be nor contain nor sit
    inside the data folder. Without `move`, an existing non-empty folder is accepted only
    when it already holds ChatImport data.
    """
    target = new.expanduser().resolve()
    source = old.expanduser().resolve()
    if target == source:
        raise ChatImportError("the new folder is the current folder")
    if target.is_relative_to(source):
        raise ChatImportError("the new folder must not be inside the current folder")
    if source.is_relative_to(target):
        raise ChatImportError("the current folder must not be inside the new folder")
    if app_base is not None:
        base = app_base.expanduser().resolve()
        if target.is_relative_to(base) or base.is_relative_to(target):
            raise ChatImportError(
                "the data folder must be apart from the application folder, which holds "
                "the Telegram session"
            )
    if not move and target.is_dir() and any(target.iterdir()) and not _looks_like_data_root(target):
        raise ChatImportError(f"{target} is not empty and holds no ChatImport data")
    probe = target / f".chatimport-probe-{uuid.uuid4().hex}"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
    except OSError as error:
        raise ChatImportError(f"cannot write to {target}: {error}") from error
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    warnings: list[str] = []
    if is_cloud_synced(target):
        warnings.append(
            "the folder is inside OneDrive; sync may lock or duplicate data files, "
            "and it uploads sender names"
        )
    return warnings


def _tree_stats(path: Path) -> tuple[int, int]:
    """Files (links counted as files, never followed) and their total size."""
    files = 0
    size = 0
    for entry in walk_files(path):
        files += 1
        size += entry.stat(follow_symlinks=False).st_size
    return files, size


def _refuse_junctions(path: Path) -> None:
    """A directory junction cannot be copied as a link: refuse before copying anything."""
    for entry in walk_files(path):
        if entry.is_junction():
            raise ChatImportError(
                f"{entry.path} is a directory junction; remove it before moving the data folder"
            )


def _clear_empty_target(new: Path) -> None:
    if not new.exists():
        return
    if not new.is_dir() or any(new.iterdir()):
        raise ChatImportError(f"{new} already exists and is not empty")
    new.rmdir()


def _same_volume(old: Path, new: Path) -> bool:
    return old.stat().st_dev == new.parent.stat().st_dev


def _move_sync(old: Path, new: Path) -> None:
    if not old.is_dir():
        return
    new.parent.mkdir(parents=True, exist_ok=True)
    _clear_empty_target(new)
    if _same_volume(old, new):
        try:
            old.replace(new)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
        else:
            return
    _refuse_junctions(old)
    try:
        shutil.copytree(old, new, symlinks=True)
        if _tree_stats(old) != _tree_stats(new):
            raise ChatImportError("the copy does not match the original; the old folder is kept")
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    try:
        shutil.rmtree(old)
    except OSError:
        log.warning("the old data folder could not be fully deleted")


async def move_root(old: Path, new: Path, *, move: bool) -> None:
    """Move the data folder; with `move=False` the data is left where it is."""
    if not move:
        return
    await asyncio.to_thread(_move_sync, old, new)
