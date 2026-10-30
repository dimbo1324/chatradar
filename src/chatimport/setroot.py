"""Changing the output folder (spec §7.3): validation and moving the data."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import os
import shutil
import uuid
from typing import TYPE_CHECKING

from chatimport.ports import ChatImportError

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)


def validate_new_root(new: Path, old: Path) -> list[str]:
    """Raise when `new` cannot be used; return warnings for a usable one."""
    target = new.expanduser().resolve()
    source = old.expanduser().resolve()
    if target == source:
        raise ChatImportError("the new folder is the current folder")
    if target.is_relative_to(source):
        raise ChatImportError("the new folder must not be inside the current folder")
    if source.is_relative_to(target):
        raise ChatImportError("the current folder must not be inside the new folder")
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
    if any("onedrive" in part.casefold() for part in target.parts):
        warnings.append("the folder is inside OneDrive; sync may lock or duplicate data files")
    return warnings


def _tree_stats(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    stack = [str(path)]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                else:
                    files += 1
                    size += entry.stat(follow_symlinks=False).st_size
    return files, size


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
    try:
        shutil.copytree(old, new)
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
