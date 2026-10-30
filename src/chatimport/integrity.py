"""`chatimport check [--repair]`: compare the JSONL files, `state.json` and media (spec §9.1).

Offline only: the caller holds the instance lock. Repairs go through the storage package.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from chatimport.ports import ChatImportError
from chatimport.records import MediaSavedRecord, MessageRecord
from chatimport.storage.layout import (
    STATE_FILE,
    iter_chat_folders,
    list_parts,
    parse_part_name,
)
from chatimport.storage.reader import decode_line, scan_part
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import StateUnreadable, load_state

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from chatimport.storage.state import ChatState

log = logging.getLogger(__name__)

ERROR: Final = "error"
WARNING: Final = "warning"
INFO: Final = "info"
_SEVERITY_RANK: Final = {ERROR: 0, WARNING: 1, INFO: 2}
_FOLDER_ID_RE: Final = re.compile(r"_(-?\d+)$")


@dataclass(frozen=True, slots=True)
class CheckIssue:
    chat_id: int | None
    folder: str
    severity: str  # "error" | "warning" | "info"
    message: str


@dataclass(slots=True)
class _Analysis:
    folder: str
    chat_id: int | None = None
    issues: list[CheckIssue] = field(default_factory=list[CheckIssue])
    fixable: list[CheckIssue] = field(default_factory=list[CheckIssue])

    def add(self, severity: str, message: str, *, fixable: bool = False) -> None:
        issue = CheckIssue(self.chat_id, self.folder, severity, message)
        self.issues.append(issue)
        if fixable:
            self.fixable.append(issue)


def _folder_chat_id(folder: Path) -> int | None:
    match = _FOLDER_ID_RE.search(folder.name)
    return int(match.group(1)) if match else None


def _check_parts(folder: Path, result: _Analysis) -> int:
    seen_ids: set[int] = set()
    duplicates = 0
    missing_media = 0
    max_file_id = 0
    previous: tuple[str, int] | None = None

    for path in list_parts(folder):
        parsed = parse_part_name(path.name)
        lines = [raw for raw in (r.strip() for r in path.read_bytes().split(b"\n")) if raw]
        bad = 0
        bad_only_last = True
        first_id = 0
        last_id = 0
        unordered = 0
        for number, raw in enumerate(lines, start=1):
            record = decode_line(raw)
            if record is None:
                bad += 1
                bad_only_last = bad_only_last and number == len(lines)
                continue
            if result.chat_id is None:
                result.chat_id = record.chat_id
            if isinstance(record, MediaSavedRecord):
                if not (folder / record.file).is_file():
                    missing_media += 1
                continue
            if not isinstance(record, MessageRecord):
                continue
            first_id = first_id or record.msg_id
            if record.msg_id < last_id:
                unordered += 1
            last_id = max(last_id, record.msg_id)
            if record.msg_id in seen_ids:
                duplicates += 1
            seen_ids.add(record.msg_id)
        max_file_id = max(max_file_id, last_id)
        if bad:
            note = "" if bad_only_last else " (more than the last line; fix by hand)"
            result.add(ERROR, f"{path.name}: {bad} unparsable line(s){note}", fixable=bad_only_last)
        if unordered:
            result.add(WARNING, f"{path.name}: {unordered} message(s) out of msg_id order")
        if parsed is not None and first_id:
            if previous is not None and previous[0] == parsed[0] and first_id < previous[1]:
                result.add(
                    WARNING,
                    f"{path.name}: first id {first_id} is below the previous part's last id",
                )
            previous = (parsed[0], last_id)

    if duplicates:
        result.add(WARNING, f"{duplicates} duplicate message record(s)")
    if missing_media:
        result.add(WARNING, f"{missing_media} saved media file(s) are missing")
    return max_file_id


def _compare_state(folder: Path, state: ChatState, max_file_id: int, result: _Analysis) -> None:
    on_disk = {path.stem: path for path in list_parts(folder)}
    chunks = state.chunks
    for key in sorted(set(chunks) - set(on_disk)):
        result.add(ERROR, f"{key}: listed in state.json but the file is missing", fixable=True)
    for key in sorted(set(on_disk) - set(chunks)):
        result.add(ERROR, f"{key}: file is not listed in state.json", fixable=True)
    for key in sorted(set(chunks) & set(on_disk)):
        actual = scan_part(on_disk[key])
        recorded = chunks[key]
        if actual.records != recorded.records:
            result.add(
                ERROR,
                f"{key}: state.json has {recorded.records} records, the file has {actual.records}",
                fixable=True,
            )
        if actual.bytes != recorded.bytes:
            result.add(
                ERROR,
                f"{key}: state.json has {recorded.bytes} bytes, the file has {actual.bytes}",
                fixable=True,
            )
    if state.last_id < max_file_id:
        result.add(
            ERROR,
            f"last_id {state.last_id} is below the highest id {max_file_id} in the files",
            fixable=True,
        )


def _analyze(folder: Path) -> _Analysis:
    result = _Analysis(folder=folder.name)
    try:
        state = load_state(folder)
    except StateUnreadable as error:
        result.add(ERROR, f"{STATE_FILE} cannot be read now ({error.__cause__}); try again")
        _check_parts(folder, result)
        return result
    if state is not None:
        result.chat_id = state.chat_id
    for stray in sorted(folder.glob("*.jsonl")):
        if parse_part_name(stray.name) is None:
            result.add(WARNING, f"{stray.name}: name does not match YYYY-MM_NNN.jsonl")
    max_file_id = _check_parts(folder, result)
    if state is None:
        kind = "unparsable" if (folder / STATE_FILE).exists() else "missing"
        result.add(ERROR, f"{STATE_FILE} is {kind}", fixable=True)
    else:
        _compare_state(folder, state, max_file_id, result)
    return result


def _is_chat_folder(folder: Path) -> bool:
    """A folder with a state or part files; anything else under the root is not ours."""
    return (folder / STATE_FILE).exists() or bool(list_parts(folder))


def _leftovers(folder: Path, *, repair: bool) -> list[CheckIssue]:
    """Temp files of interrupted writes in a chat folder."""
    found: list[CheckIssue] = []
    for tmp in sorted(folder.glob(".*.tmp")):
        if not repair:
            found.append(CheckIssue(None, folder.name, INFO, f"{tmp.name}: leftover temp file"))
            continue
        try:
            tmp.unlink()
        except OSError:
            log.warning("cannot delete a leftover temp file", extra={"folder": folder.name})
            found.append(CheckIssue(None, folder.name, WARNING, f"{tmp.name}: cannot delete"))
        else:
            found.append(CheckIssue(None, folder.name, INFO, f"{tmp.name}: leftover deleted"))
    return found


def _check_folder(folder: Path, *, repair: bool, now: datetime) -> list[CheckIssue]:
    if not _is_chat_folder(folder):
        return [CheckIssue(None, folder.name, WARNING, "not a chat folder; left alone")]
    leftovers = _leftovers(folder, repair=repair)
    analysis = _analyze(folder)
    issues = analysis.issues
    if repair and analysis.fixable:
        fallback = analysis.chat_id if analysis.chat_id is not None else _folder_chat_id(folder)
        try:
            recover_chat(folder, now=now, fallback_chat_id=fallback)
        except (ValueError, OSError, ChatImportError) as exc:
            log.warning("repair failed", extra={"folder": folder.name, "error": str(exc)})
            issues = [
                *issues,
                CheckIssue(analysis.chat_id, folder.name, ERROR, f"repair failed: {exc}"),
            ]
        else:
            after = _analyze(folder)
            fixed = [
                CheckIssue(i.chat_id, i.folder, INFO, f"repaired: {i.message}")
                for i in analysis.fixable
            ]
            issues = [*fixed, *after.issues]
            analysis.chat_id = after.chat_id
    return [
        *issues,
        *(CheckIssue(analysis.chat_id, i.folder, i.severity, i.message) for i in leftovers),
    ]


def check_root(root: Path, *, repair: bool, now: datetime) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for folder in iter_chat_folders(root):
        issues.extend(_check_folder(folder, repair=repair, now=now))
    issues.sort(key=lambda i: (i.folder, _SEVERITY_RANK.get(i.severity, len(_SEVERITY_RANK))))
    return issues
