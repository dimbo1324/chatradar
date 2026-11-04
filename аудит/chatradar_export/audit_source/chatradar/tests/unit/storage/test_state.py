from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from chatimport.storage import state as state_module
from chatimport.storage.state import (
    PHASE_HEAD_BACKFILL,
    PHASE_LIVE,
    BackfillState,
    ChatState,
    ChunkInfo,
    atomic_write_bytes,
    load_state,
    new_state,
    save_state,
)
from tests.fakes import CHAT_ID, NOW
from tests.unit.storage.helpers import EMOJI, ZH


def full_state() -> ChatState:
    return ChatState(
        chat_id=CHAT_ID,
        title=f"Title {chr(0xE9)}{ZH}{EMOJI}",
        username="example_group",
        phase=PHASE_LIVE,
        updated_at=NOW,
        last_id=4512,
        floor_id=118,
        floor_reason="manual_trim_25",
        last_recheck_at=NOW - timedelta(hours=5),
        backfill=BackfillState(
            done=True, head_id=4380, oldest_done_id=2201, started_at=NOW - timedelta(days=1)
        ),
        chunks={
            "2026-10_001": ChunkInfo(520, 4000, 4512, 260111),
            "2026-09_001": ChunkInfo(1830, 2201, 3999, 912345),
        },
    )


def minimal_dict() -> dict[str, Any]:
    return {"chat_id": 5, "phase": "live", "updated_at": "2026-10-29T12:00:00Z"}


def test_new_state_starts_in_head_backfill_with_zeroes() -> None:
    state = new_state(CHAT_ID, "T", None, NOW)
    assert state.phase == PHASE_HEAD_BACKFILL
    assert (state.last_id, state.floor_id, state.floor_reason) == (0, 0, None)
    assert state.backfill == BackfillState()
    assert state.chunks == {}
    assert state.updated_at == NOW


def test_new_states_do_not_share_the_chunks_dict() -> None:
    first = new_state(1, "a", None, NOW)
    second = new_state(2, "b", None, NOW)
    first.chunks["x"] = ChunkInfo(1, 1, 1, 1)
    assert second.chunks == {}


def test_state_round_trips_through_dict() -> None:
    state = full_state()
    assert ChatState.from_dict(state.to_dict()) == state


def test_state_survives_a_real_json_round_trip_with_unicode() -> None:
    state = full_state()
    text = json.dumps(state.to_dict(), ensure_ascii=False)
    assert ChatState.from_dict(json.loads(text)) == state


def test_to_dict_has_exactly_the_documented_keys_and_z_dates() -> None:
    data = full_state().to_dict()
    assert list(data) == [
        "v",
        "chat_id",
        "title",
        "username",
        "phase",
        "last_id",
        "floor_id",
        "floor_reason",
        "last_recheck_at",
        "newest_date",
        "backfill",
        "chunks",
        "updated_at",
    ]
    assert data["updated_at"] == "2026-10-29T12:00:00Z"
    assert data["last_recheck_at"] == "2026-10-29T07:00:00Z"
    assert data["backfill"]["started_at"] == "2026-10-28T12:00:00Z"
    assert list(data["chunks"]) == ["2026-09_001", "2026-10_001"]


def test_none_dates_serialize_as_null_and_parse_back_as_none() -> None:
    state = new_state(1, "t", None, NOW)
    data = state.to_dict()
    assert data["last_recheck_at"] is None
    assert data["backfill"]["started_at"] is None
    assert data["username"] is None
    assert ChatState.from_dict(data) == state


def test_microseconds_are_truncated_and_offsets_normalized_on_write() -> None:
    odd = datetime(2026, 10, 29, 15, 0, 0, 999999, tzinfo=timezone(timedelta(hours=3)))
    data = replace(full_state(), updated_at=odd).to_dict()
    assert data["updated_at"] == "2026-10-29T12:00:00Z"


def test_from_dict_fills_every_optional_key_with_its_default() -> None:
    state = ChatState.from_dict(minimal_dict())
    assert state.title == ""
    assert state.username is None
    assert (state.last_id, state.floor_id, state.v) == (0, 0, 1)
    assert state.floor_reason is None
    assert state.last_recheck_at is None
    assert state.backfill == BackfillState()
    assert state.chunks == {}


def test_from_dict_ignores_unknown_keys() -> None:
    data = {**minimal_dict(), "future_field": [1, 2], "backfill": {"done": True, "zzz": 1}}
    state = ChatState.from_dict(data)
    assert state.backfill.done is True


@pytest.mark.parametrize("missing", ["chat_id", "phase", "updated_at"])
def test_from_dict_requires_chat_id_phase_and_updated_at(missing: str) -> None:
    data = minimal_dict()
    del data[missing]
    with pytest.raises(KeyError):
        ChatState.from_dict(data)


def test_from_dict_treats_a_null_title_as_empty() -> None:
    assert ChatState.from_dict({**minimal_dict(), "title": None}).title == ""


def test_from_dict_treats_null_backfill_and_chunks_as_defaults() -> None:
    state = ChatState.from_dict({**minimal_dict(), "backfill": None, "chunks": None})
    assert state.backfill == BackfillState()
    assert state.chunks == {}


def test_from_dict_coerces_numeric_strings() -> None:
    data = {**minimal_dict(), "chat_id": "-1001", "last_id": "7", "floor_id": 3.0}
    state = ChatState.from_dict(data)
    assert (state.chat_id, state.last_id, state.floor_id) == (-1001, 7, 3)


def test_huge_ids_survive_the_round_trip() -> None:
    state = replace(full_state(), chat_id=-(10**18), last_id=2**62)
    assert ChatState.from_dict(json.loads(json.dumps(state.to_dict()))) == state


@pytest.mark.parametrize(
    "data",
    [
        {"records": 1, "first_id": 1, "last_id": 1},
        {"records": "x", "first_id": 1, "last_id": 1, "bytes": 1},
        {"records": None, "first_id": 1, "last_id": 1, "bytes": 1},
    ],
)
def test_chunk_info_from_dict_rejects_incomplete_or_wrong_typed_data(
    data: dict[str, Any],
) -> None:
    with pytest.raises((KeyError, ValueError, TypeError)):
        ChunkInfo.from_dict(data)


def test_chunk_info_round_trip() -> None:
    chunk = ChunkInfo(3, 10, 30, 999)
    assert ChunkInfo.from_dict(chunk.to_dict()) == chunk


def test_backfill_state_empty_started_at_string_is_none() -> None:
    assert BackfillState.from_dict({"started_at": ""}).started_at is None


def test_load_state_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert load_state(tmp_path) is None
    assert load_state(tmp_path / "no_such_folder") is None


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    folder = tmp_path / "chat"
    save_state(folder, full_state())
    assert load_state(folder) == full_state()


def test_save_state_creates_the_folder_and_ends_with_a_newline(tmp_path: Path) -> None:
    folder = tmp_path / "a" / "b"
    save_state(folder, full_state())
    assert (folder / "state.json").read_bytes().endswith(b"\n")


def test_saved_state_keeps_unicode_readable_and_uses_lf(tmp_path: Path) -> None:
    save_state(tmp_path, full_state())
    raw = (tmp_path / "state.json").read_bytes()
    assert ZH.encode() in raw
    assert b"\r" not in raw


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"   \n",
        b"not json",
        b"{",
        b'{"chat_id": 1, "phase": "li',
        b"[]",
        b"null",
        b"42",
        b'"text"',
        b"{}",
        b'{"chat_id": "abc", "phase": "live", "updated_at": "2026-10-29T12:00:00Z"}',
        b'{"chat_id": 1, "phase": "live", "updated_at": null}',
        b'{"chat_id": 1, "phase": "live", "updated_at": "yesterday"}',
        b'{"chat_id": 1, "phase": "live", "updated_at": "2026-10-29T12:00:00Z", "backfill": "x"}',
        b'{"chat_id": 1, "phase": "live", "updated_at": "2026-10-29T12:00:00Z", "chunks": [1]}',
        b'{"chat_id": 1, "phase": "live", "updated_at": "2026-10-29T12:00:00Z", "chunks":{"k":1}}',
        b'{"chat_id": 1, "phase": "live", "updated_at": "2026-10-29T12:00:00Z", "chunks":{"k":{}}}',
        b'{"chat_id": [1], "phase": "live", "updated_at": "2026-10-29T12:00:00Z"}',
        b"\xff\xfe\x00garbage",
        b"\x00" * 64,
    ],
)
def test_load_state_of_unusable_content_is_none_not_an_exception(
    tmp_path: Path, content: bytes
) -> None:
    (tmp_path / "state.json").write_bytes(content)
    assert load_state(tmp_path) is None


def test_load_state_of_a_truncated_valid_file_is_none(tmp_path: Path) -> None:
    save_state(tmp_path, full_state())
    path = tmp_path / "state.json"
    data = path.read_bytes()
    for cut in (1, len(data) // 2, len(data) - 3):
        path.write_bytes(data[:cut])
        assert load_state(tmp_path) is None


def test_load_state_with_a_utf8_bom_does_not_raise(tmp_path: Path) -> None:
    save_state(tmp_path, full_state())
    path = tmp_path / "state.json"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert load_state(tmp_path) in (None, full_state())


def test_load_state_of_crlf_content_still_parses(tmp_path: Path) -> None:
    save_state(tmp_path, full_state())
    path = tmp_path / "state.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert load_state(tmp_path) == full_state()


def test_load_state_when_state_json_is_a_directory_is_none(tmp_path: Path) -> None:
    (tmp_path / "state.json").mkdir()
    assert load_state(tmp_path) is None


def test_save_state_leaves_no_temp_litter(tmp_path: Path) -> None:
    save_state(tmp_path, full_state())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_save_state_overwrites_the_previous_state(tmp_path: Path) -> None:
    save_state(tmp_path, full_state())
    newer = replace(full_state(), last_id=9999)
    save_state(tmp_path, newer)
    assert load_state(tmp_path) == newer


def test_failing_replace_keeps_the_previous_state_and_cleans_the_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_state(tmp_path, full_state())
    before = (tmp_path / "state.json").read_bytes()

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk says no")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk says no"):
        save_state(tmp_path, replace(full_state(), last_id=1))
    monkeypatch.undo()
    assert (tmp_path / "state.json").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
    assert load_state(tmp_path) == full_state()


def test_failing_fsync_never_publishes_a_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_state(tmp_path, full_state())
    before = (tmp_path / "state.json").read_bytes()

    def broken(_fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(OSError, match="fsync failed"):
        save_state(tmp_path, replace(full_state(), last_id=1))
    monkeypatch.undo()
    assert (tmp_path / "state.json").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_failure_on_the_very_first_save_leaves_no_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="nope"):
        save_state(tmp_path, full_state())
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []
    assert load_state(tmp_path) is None


def test_atomic_write_survives_a_failing_cleanup_and_raises_the_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "data.bin"

    def broken_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    def broken_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", broken_replace)
    monkeypatch.setattr(Path, "unlink", broken_unlink)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_bytes(target, b"payload")
    monkeypatch.undo()
    assert not target.exists()


def test_atomic_write_replaces_an_existing_file_and_handles_empty_and_large_payloads(
    tmp_path: Path,
) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"")
    assert target.read_bytes() == b""
    big = os.urandom(3_000_000)
    atomic_write_bytes(target, big)
    assert target.read_bytes() == big
    assert [p.name for p in tmp_path.iterdir()] == ["data.bin"]


def test_atomic_write_temp_file_lives_next_to_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []
    real = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen.append((str(src), str(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    atomic_write_bytes(tmp_path / "x.json", b"1")
    ((src, dst),) = seen
    assert Path(src).parent == Path(dst).parent == tmp_path
    assert Path(src).name.startswith(".")
    assert Path(src).name.endswith(".tmp")


def test_phase_constants_are_distinct_strings() -> None:
    names = [
        state_module.PHASE_RECOVER,
        state_module.PHASE_HEAD_BACKFILL,
        state_module.PHASE_CATCH_UP,
        state_module.PHASE_LIVE,
        state_module.PHASE_PAUSED,
        state_module.PHASE_NO_ACCESS,
    ]
    assert len(set(names)) == len(names)
