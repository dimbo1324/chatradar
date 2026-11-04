from __future__ import annotations

import json
import logging
import shutil
from typing import TYPE_CHECKING

from chatimport.ports import DeletedMessagesEvent, EditedMessageEvent, NewMessageEvent
from chatimport.router import UNROUTED_DELETES_FILE, Router
from chatimport.runtime import ChatRegistry
from tests.fakes import CHAT_ID, NOW, FakeClock, msg
from tests.unit.service.helpers import StubController

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def make_router(tmp_path: Path, *controllers: StubController) -> tuple[Router, Path]:
    registry = ChatRegistry()
    for controller in controllers:
        registry.add(controller)
    root = tmp_path / "ChatImport"
    return Router(registry, root, clock=FakeClock()), root


async def test_events_reach_only_the_matching_chat_in_arrival_order(tmp_path: Path) -> None:
    first, second = StubController(CHAT_ID), StubController(-1009)
    router, _ = make_router(tmp_path, first, second)
    events = [
        NewMessageEvent(msg(1)),
        EditedMessageEvent(msg(1, text="x")),
        NewMessageEvent(msg(7, chat_id=-1009)),
        DeletedMessagesEvent(CHAT_ID, (1,)),
        NewMessageEvent(msg(2)),
    ]

    for event in events:
        await router.handle(event)

    assert first.events == [events[0], events[1], events[3], events[4]]
    assert second.events == [events[2]]


async def test_events_of_unknown_chats_are_dropped_silently(tmp_path: Path) -> None:
    controller = StubController(CHAT_ID)
    router, root = make_router(tmp_path, controller)

    await router.handle(NewMessageEvent(msg(1, chat_id=-555)))
    await router.handle(EditedMessageEvent(msg(1, chat_id=-555)))
    await router.handle(DeletedMessagesEvent(-555, (1, 2)))

    assert controller.events == []
    assert not root.exists()


async def test_deleted_event_with_known_chat_id_is_routed_not_stored(tmp_path: Path) -> None:
    controller = StubController(CHAT_ID)
    router, root = make_router(tmp_path, controller)

    await router.handle(DeletedMessagesEvent(CHAT_ID, (3, 4)))

    assert len(controller.events) == 1
    assert not (root / UNROUTED_DELETES_FILE).exists()


async def test_deletion_without_chat_id_is_appended_as_valid_jsonl(tmp_path: Path) -> None:
    router, root = make_router(tmp_path, StubController(CHAT_ID))

    await router.handle(DeletedMessagesEvent(None, (5, 6, 2**62)))
    await router.handle(DeletedMessagesEvent(None, (9,)))

    raw = (root / UNROUTED_DELETES_FILE).read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.decode().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "v": 1,
        "kind": "delete",
        "chat_id": None,
        "msg_ids": [5, 6, 2**62],
        "detected_by": "event",
        "fetched_at": "2026-10-29T12:00:00Z",
    }
    assert json.loads(lines[1])["msg_ids"] == [9]


async def test_unrouted_delete_is_never_forwarded_to_a_chat(tmp_path: Path) -> None:
    controller = StubController(CHAT_ID)
    router, _ = make_router(tmp_path, controller)

    await router.handle(DeletedMessagesEvent(None, (1,)))

    assert controller.events == []


async def test_unrouted_file_is_closed_and_the_root_can_be_deleted_at_once(
    tmp_path: Path,
) -> None:
    router, root = make_router(tmp_path)

    await router.handle(DeletedMessagesEvent(None, (1,)))
    shutil.rmtree(root)

    assert not root.exists()


async def test_unrouted_delete_creates_a_missing_root_and_keeps_old_lines(
    tmp_path: Path,
) -> None:
    router, root = make_router(tmp_path)
    assert not root.exists()

    await router.handle(DeletedMessagesEvent(None, (1,)))
    await router.handle(DeletedMessagesEvent(None, ()))

    lines = (root / UNROUTED_DELETES_FILE).read_text().splitlines()
    assert [json.loads(line)["msg_ids"] for line in lines] == [[1], []]


async def test_unrouted_delete_timestamp_follows_the_injected_clock(tmp_path: Path) -> None:
    clock = FakeClock(NOW)
    router = Router(ChatRegistry(), tmp_path / "r", clock=clock)
    await router.handle(DeletedMessagesEvent(None, (1,)))
    clock.advance(hours=3, seconds=7)
    await router.handle(DeletedMessagesEvent(None, (2,)))

    lines = (tmp_path / "r" / UNROUTED_DELETES_FILE).read_text().splitlines()
    assert [json.loads(line)["fetched_at"] for line in lines] == [
        "2026-10-29T12:00:00Z",
        "2026-10-29T15:00:07Z",
    ]


async def test_controller_exception_is_swallowed_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken, healthy = StubController(CHAT_ID), StubController(-1009)
    broken.fail_submit = RuntimeError("boom")
    router, _ = make_router(tmp_path, broken, healthy)

    with caplog.at_level(logging.ERROR, logger="chatimport.router"):
        await router.handle(NewMessageEvent(msg(1)))
        await router.handle(NewMessageEvent(msg(1, chat_id=-1009)))

    assert len(healthy.events) == 1
    assert "router failed on NewMessageEvent" in caplog.text


async def test_storage_failure_for_unrouted_delete_is_swallowed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the root should be")
    router = Router(ChatRegistry(), blocker / "root", clock=FakeClock())

    with caplog.at_level(logging.ERROR, logger="chatimport.router"):
        await router.handle(DeletedMessagesEvent(None, (1,)))

    assert "router failed on DeletedMessagesEvent" in caplog.text


async def test_log_output_never_contains_message_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = StubController(CHAT_ID)
    broken.fail_submit = RuntimeError("boom")
    router, _ = make_router(tmp_path, broken)

    with caplog.at_level(logging.DEBUG):
        await router.handle(NewMessageEvent(msg(1, text="SECRET-BODY")))

    assert "SECRET-BODY" not in caplog.text
