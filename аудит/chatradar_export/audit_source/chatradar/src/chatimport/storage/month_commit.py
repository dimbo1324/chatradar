"""Replacing every part of one month as a single crash-safe step.

Each part is atomic on its own, but a month of several parts is not: a crash between two
replaces would lose the records that moved from one part into the next. So the new parts are
first staged as `.<part>.new`, then a journal `.<month>.commit.json` is written atomically,
and only then are the staged files moved into place and the surplus parts deleted. Recovery
finishes a journalled commit and drops staged files that never got a journal.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import TYPE_CHECKING, Final

from chatimport.records import DECODE_ERRORS
from chatimport.storage.fileio import replace_file, unlink_file
from chatimport.storage.layout import list_parts, parse_part_name, part_file_name

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

log = logging.getLogger(__name__)

JOURNAL_SUFFIX: Final = ".commit.json"
STAGED_SUFFIX: Final = ".new"

type WriteBytes = Callable[[Path, bytes], None]


def staged_path(folder: Path, month: str, number: int) -> Path:
    return folder / f".{part_file_name(month, number)}{STAGED_SUFFIX}"


def journal_path(folder: Path, month: str) -> Path:
    return folder / f".{month}{JOURNAL_SUFFIX}"


def month_parts(folder: Path, month: str) -> list[Path]:
    return [
        p
        for p in list_parts(folder)
        if (parsed := parse_part_name(p.name)) is not None and parsed[0] == month
    ]


def commit_month(folder: Path, month: str, payloads: Sequence[bytes], write: WriteBytes) -> None:
    """Make `payloads` the parts `001..N` of `month` and delete any higher part numbers."""
    existing = month_parts(folder, month)
    if len(payloads) == 1 and all(p.name == part_file_name(month, 1) for p in existing):
        write(folder / part_file_name(month, 1), payloads[0])
        return
    staged: list[Path] = []
    try:
        for number, payload in enumerate(payloads, start=1):
            path = staged_path(folder, month, number)
            write(path, payload)
            staged.append(path)
        record = {"month": month, "parts": len(payloads)}
        write(journal_path(folder, month), json.dumps(record).encode("utf-8"))
    except BaseException:
        for path in staged:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        raise
    finish_commit(folder, month, len(payloads))


def finish_commit(folder: Path, month: str, count: int) -> None:
    """Idempotent: move every staged part into place, drop parts above `count`, then the
    journal. Safe to run again after a crash at any point."""
    for number in range(1, count + 1):
        staged = staged_path(folder, month, number)
        if staged.exists():
            replace_file(staged, folder / part_file_name(month, number))
    for path in month_parts(folder, month):
        parsed = parse_part_name(path.name)
        if parsed is not None and parsed[1] > count:
            unlink_file(path, missing_ok=True)
    unlink_file(journal_path(folder, month), missing_ok=True)


def _read_journal(path: Path) -> tuple[str, int] | None:
    try:
        data = json.loads(path.read_bytes())
        month, count = str(data["month"]), int(data["parts"])
    except (*DECODE_ERRORS, AttributeError):
        return None
    if parse_part_name(part_file_name(month, 1)) is None or count < 1:
        return None
    return month, count


def replay_month(folder: Path, month: str) -> None:
    """Finish an interrupted commit of `month`, if there is one."""
    path = journal_path(folder, month)
    if path.exists():
        parsed = _read_journal(path)
        if parsed is not None:
            finish_commit(folder, *parsed)


def replay_commits(folder: Path) -> list[str]:
    """Finish every journalled commit in the folder and delete staged parts without one;
    returns the months that were completed."""
    finished: list[str] = []
    for journal in sorted(folder.glob(f".*{JOURNAL_SUFFIX}")):
        parsed = _read_journal(journal)
        if parsed is None:
            log.warning("dropped a broken month journal", extra={"folder": folder.name})
            unlink_file(journal, missing_ok=True)
            continue
        finish_commit(folder, *parsed)
        finished.append(parsed[0])
    for leftover in folder.glob(f".*.jsonl{STAGED_SUFFIX}"):
        with contextlib.suppress(OSError):
            leftover.unlink()
    if finished:
        log.warning(
            "finished interrupted month rewrites", extra={"folder": folder.name, "months": finished}
        )
    return finished
