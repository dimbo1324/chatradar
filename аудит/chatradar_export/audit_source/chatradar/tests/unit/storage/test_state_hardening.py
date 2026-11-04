from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chatimport.ports import ChatImportError
from chatimport.storage.layout import find_chat_folder
from chatimport.storage.state import (
    PHASE_LIVE,
    ChunkInfo,
    Phase,
    StateUnreadable,
    load_state,
    save_state,
)
from tests.unit.storage.helpers import fresh_state

INFO = ChunkInfo(records=2, first_id=1, last_id=2, bytes=10)


def write_chunks(folder: Path, chunks: dict[str, object]) -> None:
    data = fresh_state().to_dict()
    data["chunks"] = chunks
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "state.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    "bad_key",
    ["../../victim", "C:/x/y", "/abs/2026-10_001", "2026-10", "2026-13_001", "2026-10_000", "x"],
)
def test_chunk_keys_that_are_not_part_names_are_dropped(
    tmp_path: Path, bad_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    write_chunks(tmp_path, {bad_key: INFO.to_dict(), "2026-10_001": INFO.to_dict()})
    with caplog.at_level("WARNING"):
        state = load_state(tmp_path)
    assert state is not None
    assert state.chunks == {"2026-10_001": INFO}
    assert "invalid part names" in caplog.text


@pytest.mark.parametrize(
    "error", [PermissionError(13, "sharing violation"), OSError(5, "I/O error")]
)
def test_a_state_that_cannot_be_read_now_raises_instead_of_looking_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    save_state(tmp_path, fresh_state())
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "state.json":
            raise error
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    with pytest.raises(StateUnreadable, match="cannot be read now") as caught:
        load_state(tmp_path)
    assert isinstance(caught.value, ChatImportError)
    assert caught.value.folder == tmp_path
    assert caught.value.__cause__ is error


def test_missing_folder_or_a_file_in_place_of_the_folder_is_missing(tmp_path: Path) -> None:
    assert load_state(tmp_path / "absent") is None
    not_a_folder = tmp_path / "file"
    not_a_folder.write_bytes(b"x")
    assert load_state(not_a_folder) is None


def test_find_chat_folder_falls_back_to_the_suffix_while_a_state_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "group_-5"
    save_state(folder, replace(fresh_state(), chat_id=-5))
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "state.json":
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    assert find_chat_folder(tmp_path, -5) == folder
    assert find_chat_folder(tmp_path, -6) is None


def test_phase_values_are_the_stored_strings() -> None:
    assert PHASE_LIVE is Phase.LIVE
    assert [p.value for p in Phase] == [
        "recover",
        "head_backfill",
        "catch_up",
        "live",
        "paused",
        "no_access",
    ]
    state = replace(fresh_state(), phase=Phase.PAUSED)
    assert state.to_dict()["phase"] == "paused"


def test_total_records_sums_the_chunks() -> None:
    state = replace(fresh_state(), chunks={"2026-09_001": INFO, "2026-10_001": INFO})
    assert state.total_records == 4
    assert fresh_state().total_records == 0


def test_saved_state_has_no_unicode_line_breaks_and_survives_a_lone_surrogate(
    tmp_path: Path,
) -> None:
    title = f"a{chr(0x2028)}b\ud800c"
    save_state(tmp_path, replace(fresh_state(), title=title))
    raw = (tmp_path / "state.json").read_bytes()
    assert chr(0x2028).encode() not in raw
    loaded = load_state(tmp_path)
    assert loaded is not None
    assert loaded.title == title
