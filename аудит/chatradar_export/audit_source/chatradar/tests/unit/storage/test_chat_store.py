from __future__ import annotations

import shutil
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from chatimport.records import EditRecord, MessageRecord, Record
from chatimport.storage import chat_store
from chatimport.storage.chat_store import ChatStore, StateGone
from chatimport.storage.state import load_state, save_state
from tests.fakes import CHAT_ID, NOW, FakeClock, msg
from tests.unit.storage.helpers import assert_state_matches_files, at, fresh_state, message_ids

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

NAME = f"example_{CHAT_ID}"


def store_for(root: Path) -> ChatStore:
    return ChatStore(root, CHAT_ID, NAME, max_chunk_bytes=10**9, clock=FakeClock())


def october(msg_id: int) -> MessageRecord:
    return msg(msg_id, date=at(2026, 10, 1 + msg_id))


def test_a_new_chat_writes_into_the_default_folder(tmp_path: Path) -> None:
    store = store_for(tmp_path)
    assert store.folder == tmp_path / NAME
    assert store.load() is None
    with pytest.raises(StateGone):
        store.require()
    state = store.save(fresh_state())
    state = store.write_month(state, "2026-10", [october(1), october(2)])
    state = store.merge_month(state, "2026-10", [october(3)])
    state = store.append(state, [october(4)])
    assert state.updated_at == NOW
    assert store.require() == state
    assert message_ids(tmp_path / NAME) == [1, 2, 3, 4]
    assert_state_matches_files(tmp_path / NAME)


def test_an_existing_folder_is_found_by_its_state_and_cached(tmp_path: Path) -> None:
    folder = tmp_path / "renamed_by_hand"
    save_state(folder, fresh_state())
    store = store_for(tmp_path)
    assert store.resolve_folder() == folder
    assert store.folder == folder
    shutil.rmtree(folder)
    assert store.resolve_folder() == tmp_path / NAME


def test_recover_rebuilds_with_the_chat_id_and_title(tmp_path: Path) -> None:
    store = store_for(tmp_path)
    state = store.append(store.save(fresh_state()), [october(1)])
    (store.folder / "state.json").unlink()
    recovered = store.recover(title="Group")
    assert (recovered.chat_id, recovered.title, recovered.last_id) == (CHAT_ID, "Group", 1)
    assert load_state(store.folder) == recovered
    assert state.last_id == 1


def test_oldest_message_date_skips_edits_and_unreadable_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_for(tmp_path)
    state = store.save(fresh_state())
    state = store.append(state, [EditRecord(CHAT_ID, 9, at(2026, 8, 1), NOW)])
    state = store.append(state, [msg(5, date=at(2026, 9, 3))])
    state = store.append(state, [october(6)])
    assert store.oldest_message_date(state) == at(2026, 9, 3)

    real = chat_store.iter_part_records

    def flaky(path: Path) -> Iterator[Record]:
        if path.name.startswith("2026-09"):
            raise OSError("locked")
        return real(path)

    monkeypatch.setattr(chat_store, "iter_part_records", flaky)
    assert store.oldest_message_date(state) == at(2026, 10, 7)
    assert store.oldest_message_date(replace(state, chunks={})) is None
