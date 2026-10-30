from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from chatimport import trim as trim_module
from chatimport.records import MessageRecord, Record
from chatimport.runtime import ChatRegistry
from chatimport.storage.state import ChunkInfo, new_state, save_state
from chatimport.trim import TRIM_LOG, Trimmer, _existing_chunks  # pyright: ignore[reportPrivateUsage]
from tests.fakes import NOW, FakeClock
from tests.unit.maintenance.helpers import (
    FakeController,
    assert_state_matches_files,
    at,
    build_chat,
    message_ids,
    mmsg,
    read_state,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

CHAT = -100
OTHER = -200


def trimmer(root: Path, *controllers: FakeController) -> Trimmer:
    registry = ChatRegistry()
    for controller in controllers:
        registry.add(controller)
    return Trimmer(root, registry, clock=FakeClock(), max_chunk_bytes=1)


def each(*ids: int, month: int = 9) -> list[list[Record]]:
    return [[mmsg(i, month, chat_id=CHAT)] for i in ids]


def log_entries(root: Path) -> list[dict[str, object]]:
    path = root / TRIM_LOG
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def poison_state(chat: FakeController, key: str) -> None:
    data = json.loads((chat.folder / "state.json").read_text(encoding="utf-8"))
    data["chunks"][key] = {"records": 5, "first_id": 1, "last_id": 5, "bytes": 10}
    (chat.folder / "state.json").write_text(json.dumps(data), encoding="utf-8")


async def test_trim_ignores_chunk_keys_outside_the_folder(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, each(1, 2, 3, 4))
    victim = root / "victim.jsonl"
    victim.write_bytes(b"precious\n")
    poison_state(chat, "../../victim")
    poison_state(chat, "../victim")

    await trimmer(root, chat).trim_percent(25)
    await trimmer(root, chat).delete_oldest_part(0)

    assert victim.read_bytes() == b"precious\n"
    assert message_ids(chat) == [3, 4]


async def test_disk_trim_survives_non_part_chunk_key(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, each(1, 2))
    poison_state(chat, "not-a-part")
    part = await trimmer(root, chat).delete_oldest_part(0)
    assert part is not None
    assert part.part == "2026-09_001"


def test_existing_chunks_checks_the_name_even_for_a_state_built_in_code(tmp_path: Path) -> None:
    (tmp_path / "2026-09_001.jsonl").write_bytes(b"")
    info = ChunkInfo(1, 1, 1, 1)
    state = replace(
        new_state(CHAT, "t", None, NOW),
        chunks={"2026-09_001": info, "../2026-09_001": info, "2026-09_002": info},
    )
    assert _existing_chunks(tmp_path, state) == {"2026-09_001": info}


async def test_trim_partial_failure_keeps_state_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, each(1, 2, 3, 4))
    real = trim_module.unlink_file
    calls = 0

    def second_fails(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("locked by a reader")
        real(path, missing_ok=missing_ok)

    monkeypatch.setattr(trim_module, "unlink_file", second_fails)
    with pytest.raises(PermissionError, match="locked"):
        await trimmer(root, chat).trim_percent(75)

    state = read_state(chat)
    assert sorted(state.chunks) == ["2026-09_002", "2026-09_003", "2026-09_004"]
    assert state.floor_id == 2
    assert_state_matches_files(chat)
    (entry,) = log_entries(root)
    assert entry["parts"] == ["2026-09_001"]
    assert entry["records"] == 1


async def test_service_trim_includes_disabled_chat_folders(tmp_path: Path) -> None:
    root = tmp_path / "root"
    active = build_chat(root, CHAT, each(1, 2), title="Active")
    disabled = build_chat(root, OTHER, [[mmsg(i, chat_id=OTHER)] for i in (1, 2)], title="Disabled")
    report = await trimmer(root, active).trim_percent(50)
    assert report.per_chat == {CHAT: 1, OTHER: 1}
    assert message_ids(disabled) == [2]

    only = await trimmer(root, active).trim_percent(50, chat_id=OTHER)
    assert only.per_chat == {}
    assert message_ids(disabled) == [2]


async def test_disk_trim_reaches_a_disabled_chat_and_skips_unreadable_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    active = build_chat(root, CHAT, [[mmsg(5, 9, chat_id=CHAT)]], title="Active")
    disabled = build_chat(root, OTHER, [[mmsg(1, 7, chat_id=OTHER)]], title="Disabled")
    broken = build_chat(root, -300, [[mmsg(1, 6, chat_id=-300)]], title="Broken")
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "state.json" and self.parent == broken.folder:
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    with caplog.at_level("WARNING"):
        part = await trimmer(root, active).delete_oldest_part(0)
    assert part is not None
    assert part.chat_id == OTHER
    assert message_ids(disabled) == []
    assert "unreadable" in caplog.text


async def test_a_folder_taken_over_by_a_worker_is_left_to_it(tmp_path: Path) -> None:
    root = tmp_path / "root"
    disabled = build_chat(root, OTHER, [[mmsg(i, chat_id=OTHER)] for i in (1, 2)])
    registry = ChatRegistry()
    trim = Trimmer(root, registry, clock=FakeClock(), max_chunk_bytes=1)
    handles = trim._handles()  # pyright: ignore[reportPrivateUsage]
    registry.add(disabled)
    assert not trim._still_free(handles[0])  # pyright: ignore[reportPrivateUsage]
    assert trim._still_free(disabled)  # pyright: ignore[reportPrivateUsage]


async def test_trim_without_media_does_not_parse_deleted_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, each(1, 2, 3, 4))

    def forbidden(path: Path) -> set[int]:
        raise AssertionError(f"{path.name} was decoded")

    monkeypatch.setattr(trim_module, "_message_ids", forbidden)
    report = await trimmer(root, chat).trim_percent(50)
    assert report.trimmed_records == 2
    assert message_ids(chat) == [3, 4]


async def test_cut_boundary_keeps_raw_bytes_of_kept_lines(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(i, chat_id=CHAT) for i in (1, 2, 3, 4)]])
    part = chat.folder / "2026-09_001.jsonl"
    unknown = b'{"v":1,"kind":"reaction","msg_id":4,"extra":"keep me"}\n'
    lines = part.read_bytes().splitlines(keepends=True)
    garbage = b"{cut" + bytes([10])
    part.write_bytes(garbage + b"".join(lines[:3]) + unknown + lines[3])
    state = read_state(chat)
    save_state(
        chat.folder,
        replace(
            state,
            chunks={"2026-09_001": replace(state.chunks["2026-09_001"], bytes=part.stat().st_size)},
        ),
    )

    await trimmer(root, chat).trim_percent(50)

    assert part.read_bytes() == lines[2] + unknown + lines[3]
    assert message_ids(chat) == [3, 4]


async def test_oldest_eligible_reads_only_first_message_for_old_months(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(i, 3, chat_id=CHAT) for i in range(1, 30)]])
    consumed = 0
    real = trim_module.iter_part_records

    def counting(path: Path) -> Iterator[Record]:
        nonlocal consumed
        for record in real(path):
            consumed += 1
            yield record

    monkeypatch.setattr(trim_module, "iter_part_records", counting)
    first = trimmer(root, chat)._oldest_eligible(chat, NOW)  # pyright: ignore[reportPrivateUsage]
    assert first is not None
    assert first.first_date == at(2026, 3, 10, 1)
    assert consumed == 1


async def test_oldest_eligible_of_a_part_without_messages_uses_the_month_start(
    tmp_path: Path,
) -> None:
    from chatimport.records import EditRecord

    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[EditRecord(CHAT, 1, at(2026, 2, 3), NOW)]])
    first = trimmer(root, chat)._oldest_eligible(chat, NOW)  # pyright: ignore[reportPrivateUsage]
    assert first is not None
    assert first.first_date == at(2026, 2, 1)


async def test_a_december_part_is_old_once_january_starts(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[MessageRecord(CHAT, 1, at(2025, 12, 31, 23), NOW)]])
    eligible = trimmer(root, chat)._oldest_eligible(chat, at(2026, 1, 2))  # pyright: ignore[reportPrivateUsage]
    assert eligible is not None
    assert eligible.first_date == at(2025, 12, 31, 23)


async def test_a_failure_before_any_change_saves_and_logs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, each(1, 2, 3, 4))
    before = (chat.folder / "state.json").read_bytes()

    def locked(path: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(trim_module, "unlink_file", locked)
    with pytest.raises(PermissionError):
        await trimmer(root, chat).trim_percent(50)
    assert (chat.folder / "state.json").read_bytes() == before
    assert not (root / TRIM_LOG).exists()


async def test_a_folder_a_worker_took_over_meanwhile_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    disabled = build_chat(root, OTHER, [[mmsg(i, 3, chat_id=OTHER)] for i in (1, 2)])
    registry = ChatRegistry()
    trim = Trimmer(root, registry, clock=FakeClock(), max_chunk_bytes=1)
    stale = trim._handles()  # pyright: ignore[reportPrivateUsage]
    registry.add(disabled)
    monkeypatch.setattr(trim, "_handles", lambda: stale)

    report = await trim.trim_percent(50)
    part = await trim.delete_oldest_part(0)

    assert report.per_chat == {}
    assert part is None
    assert message_ids(disabled) == [1, 2]


async def test_disk_trim_skips_an_active_chat_whose_state_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, each(1, 2, month=3))
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "state.json":
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    with caplog.at_level("WARNING"):
        assert await trimmer(root, chat).delete_oldest_part(0) is None
    assert "disk trim skipped an unreadable state" in caplog.text
