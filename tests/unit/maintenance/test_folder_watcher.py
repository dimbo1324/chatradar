from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

import pytest

from chatimport.config import WatchConfig
from chatimport.guards.folders import FolderWatcher
from chatimport.runtime import ChatRegistry, Level
from chatimport.storage.layout import STATE_FILE, list_parts
from chatimport.storage.state import load_state
from tests.fakes import NOW, FakeClock, RecordingNotifier
from tests.unit.maintenance.helpers import (
    FakeController,
    assert_state_matches_files,
    build_chat,
    drive,
    message_ids,
    mmsg,
    read_state,
)

if TYPE_CHECKING:
    from pathlib import Path


def watcher_for(
    root: Path,
    *controllers: FakeController,
    confirm_checks: int = 2,
    clock: FakeClock | None = None,
) -> tuple[FolderWatcher, RecordingNotifier]:
    registry = ChatRegistry()
    for controller in controllers:
        registry.add(controller)
    notifier = RecordingNotifier()
    watcher = FolderWatcher(
        root,
        registry,
        WatchConfig(check_every_seconds=10, confirm_checks=confirm_checks),
        clock=clock or FakeClock(),
        notifier=notifier,
    )
    return watcher, notifier


def chat_with_parts(root: Path, chat_id: int = -1, title: str = "Group") -> FakeController:
    batches = [[mmsg(i, chat_id=chat_id)] for i in (1, 2, 3)]
    return build_chat(root, chat_id, batches, title=title)


def refetches(controller: FakeController) -> int:
    return controller.calls.count("request_refetch")


async def test_folder_missing_for_confirm_checks_in_a_row_requests_one_refetch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, notifier = watcher_for(root, chat)
    await watcher.check_once()

    shutil.rmtree(chat.folder)
    await watcher.check_once()
    assert refetches(chat) == 0
    await watcher.check_once()
    assert refetches(chat) == 1
    for _ in range(5):
        await watcher.check_once()

    assert refetches(chat) == 1
    assert [(n.level, n.title) for n in notifier.notes] == [(Level.WARNING, "Folder watch")]
    assert str(chat.chat_id) in notifier.notes[0].message
    assert "Group" not in notifier.notes[0].message


@pytest.mark.parametrize("confirm", [1, 2, 3, 5])
async def test_the_confirmation_threshold_is_exactly_confirm_checks(
    tmp_path: Path, confirm: int
) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat, confirm_checks=confirm)
    await watcher.check_once()
    shutil.rmtree(chat.folder)

    for _ in range(confirm - 1):
        await watcher.check_once()
    assert refetches(chat) == 0
    await watcher.check_once()

    assert refetches(chat) == 1


async def test_a_single_miss_followed_by_the_folder_reappearing_resets_the_count(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    aside = tmp_path / "aside"
    watcher, _ = watcher_for(root, chat)
    await watcher.check_once()

    chat.folder.rename(aside)
    await watcher.check_once()
    aside.rename(chat.folder)
    await watcher.check_once()
    chat.folder.rename(aside)
    await watcher.check_once()

    assert refetches(chat) == 0
    aside.rename(chat.folder)
    await watcher.check_once()
    assert refetches(chat) == 0


async def test_a_folder_that_was_never_created_is_not_refetched(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    chat = FakeController(-1, root / "never_-1")
    watcher, notifier = watcher_for(root, chat)

    for _ in range(6):
        await watcher.check_once()

    assert chat.calls == []
    assert notifier.notes == []


async def test_after_the_refetch_a_recreated_folder_is_watched_again(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    await watcher.check_once()
    shutil.rmtree(chat.folder)
    await watcher.check_once()
    await watcher.check_once()
    assert refetches(chat) == 1

    chat_with_parts(root)
    await watcher.check_once()
    shutil.rmtree(chat.folder)
    await watcher.check_once()
    assert refetches(chat) == 1
    await watcher.check_once()

    assert refetches(chat) == 2


async def test_root_before_it_ever_existed_is_not_created(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = FakeController(-1, root / "x_-1")
    watcher, notifier = watcher_for(root, chat)

    for _ in range(5):
        await watcher.check_once()

    assert not root.exists()
    assert notifier.notes == []


async def test_root_deleted_is_recreated_and_every_chat_refetched_once(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = chat_with_parts(root, -1, "A")
    b = chat_with_parts(root, -2, "B")
    watcher, notifier = watcher_for(root, a, b)
    await watcher.check_once()

    shutil.rmtree(root)
    await watcher.check_once()
    assert not root.exists()
    assert refetches(a) == 0
    await watcher.check_once()

    assert root.is_dir()
    assert refetches(a) == refetches(b) == 1
    assert [n.level for n in notifier.notes] == [Level.WARNING]
    for _ in range(5):
        await watcher.check_once()
    assert refetches(a) == refetches(b) == 1
    assert len(notifier.notes) == 1


async def test_root_missing_for_one_check_only_does_not_refetch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    aside = tmp_path / "aside"
    watcher, _ = watcher_for(root, chat)
    await watcher.check_once()

    root.rename(aside)
    await watcher.check_once()
    aside.rename(root)
    await watcher.check_once()
    root.rename(aside)
    await watcher.check_once()

    assert refetches(chat) == 0
    assert not root.exists()


async def test_only_state_json_deleted_rebuilds_it_without_a_refetch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root, -42, "Real Title")
    watcher, notifier = watcher_for(root, chat)
    await watcher.check_once()
    (chat.folder / STATE_FILE).unlink()

    await watcher.check_once()

    assert refetches(chat) == 0
    state = read_state(chat)
    assert state.chat_id == -42
    assert state.title == "Real Title"
    assert state.floor_id == 1
    assert state.last_id == 3
    assert message_ids(chat) == [1, 2, 3]
    assert_state_matches_files(chat)
    assert notifier.notes == []


async def test_corrupt_state_json_is_rebuilt_from_the_parts(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    (chat.folder / STATE_FILE).write_text("{not json", encoding="utf-8")

    await watcher.check_once()

    assert read_state(chat).last_id == 3
    assert refetches(chat) == 0


async def test_state_and_parts_both_absent_in_an_existing_folder_does_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    folder = root / "empty_-1"
    folder.mkdir(parents=True)
    chat = FakeController(-1, folder)
    watcher, _ = watcher_for(root, chat)

    await watcher.check_once()

    assert list(folder.iterdir()) == []
    assert chat.calls == []


async def test_consistent_state_is_left_untouched(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    before = (chat.folder / STATE_FILE).read_bytes()

    for _ in range(3):
        await watcher.check_once()

    assert (chat.folder / STATE_FILE).read_bytes() == before


async def test_deleted_part_files_raise_the_floor_like_a_manual_trim(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    list_parts(chat.folder)[0].unlink()

    await watcher.check_once()

    state = read_state(chat)
    assert state.floor_id == 2
    assert state.floor_reason == "manual_delete"
    assert sorted(state.chunks) == ["2026-09_002", "2026-09_003"]
    assert state.last_id == 3
    assert refetches(chat) == 0
    assert_state_matches_files(chat)


async def test_the_newest_part_deleted_keeps_last_id_so_nothing_is_refetched(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    list_parts(chat.folder)[-1].unlink()

    await watcher.check_once()

    state = read_state(chat)
    assert state.last_id == 3
    assert sorted(state.chunks) == ["2026-09_001", "2026-09_002"]


async def test_all_part_files_deleted_floor_jumps_over_everything_known(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    for path in list_parts(chat.folder):
        path.unlink()

    await watcher.check_once()

    state = read_state(chat)
    assert state.chunks == {}
    assert state.floor_id == 3
    assert state.last_id == 3


async def test_an_unknown_part_added_by_hand_is_adopted(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    source = list_parts(chat.folder)[0]
    extra = chat.folder / "2026-08_001.jsonl"
    extra.write_bytes(source.read_bytes())

    await watcher.check_once()

    state = read_state(chat)
    assert "2026-08_001" in state.chunks
    assert_state_matches_files(chat)


async def test_service_folders_and_unregistered_chats_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    stray = chat_with_parts(root, -99, "Stray")
    (stray.folder / STATE_FILE).unlink()
    service = root / "_service"
    service.mkdir()
    (root / "_trim_log.jsonl").write_text("{}\n", encoding="utf-8")
    watcher, notifier = watcher_for(root, chat)

    for _ in range(3):
        await watcher.check_once()

    assert load_state(stray.folder) is None
    assert sorted(p.name for p in service.iterdir()) == []
    assert notifier.notes == []


async def test_recovery_waits_for_the_controller_lock(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    (chat.folder / STATE_FILE).unlink()

    async with chat.lock:
        task = asyncio.create_task(watcher.check_once())
        for _ in range(20):
            await asyncio.sleep(0)
        assert not task.done()
        assert load_state(chat.folder) is None

    await task
    assert read_state(chat).last_id == 3


async def test_folder_deleted_while_waiting_for_the_lock_is_not_resurrected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    watcher, _ = watcher_for(root, chat)
    (chat.folder / STATE_FILE).unlink()

    async with chat.lock:
        task = asyncio.create_task(watcher.check_once())
        for _ in range(20):
            await asyncio.sleep(0)
        shutil.rmtree(chat.folder)

    await task

    assert not chat.folder.exists()
    assert refetches(chat) == 0


async def test_run_checks_at_the_configured_pace_and_survives_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    clock = FakeClock()
    watcher, _ = watcher_for(root, clock=clock)
    calls = {"n": 0}
    original = watcher.check_once

    async def flaky() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("explorer is busy")
        await original()

    monkeypatch.setattr(watcher, "check_once", flaky)

    with caplog.at_level("ERROR"):
        await drive(watcher.run, clock, cycles=3)

    assert calls["n"] == 3
    assert clock.sleeps == [10, 10, 10]
    assert caplog.text.count("folder watcher check failed") == 1


async def test_recovery_stamps_the_injected_clock(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = chat_with_parts(root)
    clock = FakeClock()
    watcher, _ = watcher_for(root, chat, clock=clock)
    (chat.folder / STATE_FILE).unlink()

    await watcher.check_once()

    assert read_state(chat).updated_at == NOW
