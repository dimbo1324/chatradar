"""Crash-safe file primitives shared by every writer: temp file next to the target, fsync,
`os.replace`; fsynced appends; a tree walk that never follows links.

On Windows a reader that holds a file open (antivirus, the search indexer, a backup agent)
makes `os.replace` and `unlink` fail with a sharing violation for a moment, so both are
retried briefly before the error is raised.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
import uuid
from typing import IO, TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from pathlib import Path

RETRY_DELAYS: Final = (0.05, 0.1, 0.2, 0.4, 0.8)
RETRY_SHARING_VIOLATIONS: bool = sys.platform == "win32"
PRIVATE_FILE_MODE: Final = 0o600


def _retrying[T](operation: Callable[[], T]) -> T:
    delays = RETRY_DELAYS if RETRY_SHARING_VIOLATIONS else ()
    for delay in delays:
        try:
            return operation()
        except PermissionError:
            time.sleep(delay)
    return operation()


def replace_file(source: Path, target: Path) -> None:
    _retrying(lambda: source.replace(target))


def unlink_file(path: Path, *, missing_ok: bool = False) -> None:
    _retrying(lambda: path.unlink(missing_ok=missing_ok))


def _temp_path(path: Path, *, unique: bool) -> Path:
    marker = f".{uuid.uuid4().hex}" if unique else ""
    return path.with_name(f".{path.name}{marker}.tmp")


def _open_new(path: Path, mode: int | None) -> IO[bytes]:
    if mode is None:
        return path.open("wb")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), mode
    )
    return os.fdopen(descriptor, "wb")


@contextlib.contextmanager
def atomic_writer(
    path: Path, *, unique: bool = False, mode: int | None = None
) -> Generator[IO[bytes]]:
    """Stream into a temp file; on success it is fsynced and replaces `path` in one step."""
    tmp = _temp_path(path, unique=unique)
    try:
        with _open_new(tmp, mode) as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            with contextlib.suppress(OSError):
                tmp.chmod(mode)
        replace_file(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def atomic_write_bytes(
    path: Path, data: bytes, *, unique: bool = False, mode: int | None = None
) -> None:
    """Temp file in the same folder, fsync, then `os.replace` (atomic on one volume).

    `unique` gives the temp file a random name, for writers that may race on one target;
    `mode` (POSIX) creates the file with those permission bits, e.g. `PRIVATE_FILE_MODE`.
    """
    with atomic_writer(path, unique=unique, mode=mode) as handle:
        handle.write(data)


def append_line(path: Path, line: bytes) -> None:
    """Append bytes and fsync before returning; the file is closed again right away."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def walk_files(
    root: Path, *, skip_dir: Callable[[os.DirEntry[str]], bool] | None = None
) -> Iterator[os.DirEntry[str]]:
    """Every non-directory entry under `root`; links (and junctions) are yielded, never followed."""
    stack = [str(root)]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                    if skip_dir is None or not skip_dir(entry):
                        stack.append(entry.path)
                else:
                    yield entry
