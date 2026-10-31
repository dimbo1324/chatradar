from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING

import pytest

from chatimport.app import ChatImportApp
from chatimport.control import AlreadyRunning, acquire_instance_lock, service_running
from chatimport.ports import (
    ChatImportError,
    NewMessageEvent,
    ResolvedChat,
    ResolveStatus,
    SessionRevoked,
)
from chatimport.runtime import Level
from chatimport.status import StatusWriter
from chatimport.storage.layout import chat_folder_name, iter_chat_folders
from chatimport.storage.state import load_state
from chatimport.supervisor import Supervisor
from tests.fakes import NOW, RecordingNotifier, msg
from tests.unit.service.harness import Env, ManualClock, SpyGateway, library_text, make_env

if TYPE_CHECKING:
    from pathlib import Path

A, B, C = -1001, -1002, -1003


def two_chats(tmp_path: Path, **kwargs: object) -> Env:
    return make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True), ("@c", "Gamma", False)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat"), "@c": (C, "Gamma chat")},
        messages={A: 4, B: 3, C: 2},
        **kwargs,  # type: ignore[arg-type]
    )


def folder_ids(env: Env) -> list[int]:
    ids: list[int] = []
    for folder in iter_chat_folders(env.root):
        state = load_state(folder)
        assert state is not None
        ids.append(state.chat_id)
    return sorted(ids)


async def test_run_connects_starts_one_worker_per_enabled_chat_and_stops_cleanly(
    tmp_path: Path,
) -> None:
    env = two_chats(tmp_path)
    task = env.start()

    await env.wait_live(A, B)
    chats = await env.chats()
    assert set(chats) == {A, B}
    assert env.gateway.connected
    await env.stop()

    assert task.done()
    assert not env.gateway.connected
    assert env.gateway.calls[-1] == ("disconnect", ())
    assert folder_ids(env) == sorted([A, B])
    assert not service_running(env.ctx.paths.lock_file)


async def test_event_handler_is_registered_before_any_worker_touches_telegram(
    tmp_path: Path,
) -> None:
    env = two_chats(tmp_path)
    env.start()

    await env.wait_live(A, B)
    await env.stop()

    assert env.gateway.handlers_at
    assert all(count == 1 for _, count in env.gateway.handlers_at)
    names = [name for name, _ in env.gateway.calls]
    assert names.index("connect") < names.index("resolve") < names.index("newest_id")


async def test_folders_are_named_by_library_name_and_chat_id(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()

    await env.wait_live(A, B)
    await env.stop()

    names = sorted(f.name for f in iter_chat_folders(env.root))
    assert names == sorted([chat_folder_name("Alpha", A), chat_folder_name("Beta", B)])


async def test_disabled_chat_is_never_resolved_or_stored(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()

    await env.wait_live(A, B)
    await env.stop()

    assert ("resolve", ("@c",)) not in env.gateway.calls
    assert C not in folder_ids(env)


async def test_final_status_file_says_stopped_and_lists_the_chats(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()
    await env.wait_live(A, B)

    await env.stop()

    data = json.loads((env.root / "_status.json").read_text("utf-8"))
    assert data["service"] == "stopped"
    assert data["total_bytes"] > 0


async def test_unresolved_chats_get_no_worker_but_a_status_error_and_a_warning(
    tmp_path: Path,
) -> None:
    env = make_env(
        tmp_path,
        library=library_text(
            ("@ok", None, True),
            ("@private", None, True),
            ("@nobody", None, True),
            ("@human", None, True),
            ("@twins", None, True),
        ),
        chats={"@ok": (A, "Ok")},
    )
    env.gateway.refs["@private"] = ResolvedChat("@private", ResolveStatus.NEED_TO_JOIN)
    env.gateway.refs["@human"] = ResolvedChat("@human", ResolveStatus.NOT_A_CHAT)
    env.gateway.refs["@twins"] = ResolvedChat(
        "@twins", ResolveStatus.AMBIGUOUS, detail="2 chats match"
    )
    env.start()

    await env.wait_live(A)
    data = await env.status()
    await env.stop()

    assert data is not None
    assert [c["chat_id"] for c in data["chats"]] == [A]
    errors = {e["source"]: e["message"] for e in data["errors"]}
    assert errors["resolve:@private"] == "@private: need_to_join"
    assert errors["resolve:@nobody"] == "@nobody: not_found"
    assert errors["resolve:@human"] == "@human: not_a_chat"
    assert errors["resolve:@twins"] == "@twins: ambiguous (2 chats match)"
    warnings = [n for n in env.notifier.notes if n.level is Level.WARNING]
    assert [n.message for n in warnings] == ["4 of 5 chats could not be resolved"]


async def test_resolve_error_other_than_session_loss_marks_the_entry_not_found(
    tmp_path: Path,
) -> None:
    env = make_env(tmp_path, library=library_text(("@ok", None, True)), chats={"@ok": (A, "Ok")})
    env.gateway.fail["resolve"] = [ChatImportError("flood")]
    env.start()

    await env.wait_running()
    data = await env.status()
    await env.stop()

    assert data is not None
    assert data["chats"] == []
    assert data["errors"] == [
        {"source": "resolve:@ok", "message": "@ok: not_found (ChatImportError)"}
    ]


async def test_retryable_unresolved_chat_is_retried_after_ten_minutes_and_started(
    tmp_path: Path,
) -> None:
    env = make_env(tmp_path, library=library_text(("@late", None, True)))
    env.gateway.refs["@late"] = ResolvedChat("@late", ResolveStatus.NEED_TO_JOIN)
    env.gateway.add_chat(A, range(1, 3))
    env.start()
    await env.wait_running()
    assert env.gateway.count("resolve") == 1

    await env.clock.advance(590)
    assert env.gateway.count("resolve") == 1
    env.gateway.refs["@late"] = ResolvedChat(
        "@late", ResolveStatus.FOUND, chat_id=A, title="Late", username="late"
    )
    await env.clock.advance(20)
    await env.wait_live(A)
    data = await env.status()
    await env.stop()

    assert env.gateway.count("resolve") == 2
    assert data is not None
    assert data["errors"] == []


async def test_non_retryable_statuses_are_not_asked_again(tmp_path: Path) -> None:
    env = make_env(tmp_path, library=library_text(("@human", None, True), ("@twins", None, True)))
    env.gateway.refs["@human"] = ResolvedChat("@human", ResolveStatus.NOT_A_CHAT)
    env.gateway.refs["@twins"] = ResolvedChat("@twins", ResolveStatus.AMBIGUOUS)
    env.start()
    await env.wait_running()

    await env.clock.advance(3000)
    await env.stop()

    assert env.gateway.count("resolve") == 2


async def test_unresolved_entry_removed_from_the_library_is_not_retried(tmp_path: Path) -> None:
    env = make_env(tmp_path, library=library_text(("@late", None, True)))
    env.gateway.refs["@late"] = ResolvedChat("@late", ResolveStatus.NEED_TO_JOIN)
    env.start()
    await env.wait_running()

    env.write_library("")
    await env.clock.advance(11)
    await env.clock.advance(700)
    data = await env.status()
    await env.stop()

    assert env.gateway.count("resolve") == 1
    assert data is not None
    assert data["errors"] == []


async def test_a_second_app_on_the_same_lock_is_refused_without_touching_telegram(
    tmp_path: Path,
) -> None:
    first = two_chats(tmp_path)
    first.start()
    await first.wait_live(A, B)
    other_gateway = SpyGateway()
    second = ChatImportApp(
        first.ctx, notifier=RecordingNotifier(), gateway=other_gateway, clock=ManualClock()
    )

    with pytest.raises(AlreadyRunning):
        await second.run()

    assert other_gateway.calls == []
    assert service_running(first.ctx.paths.lock_file)
    await first.stop()
    assert not service_running(first.ctx.paths.lock_file)


async def test_lock_can_be_taken_again_after_the_service_stopped(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()
    await env.wait_live(A, B)
    await env.stop()

    lock = acquire_instance_lock(env.ctx.paths.lock_file)
    lock.release()


async def test_broken_library_at_start_keeps_the_service_up_and_reports_it(
    tmp_path: Path,
) -> None:
    env = make_env(tmp_path, library="[[chat]\nref = ", chats={"@a": (A, "Alpha")})
    env.start()

    await env.wait_running()
    data = await env.status()

    assert data is not None
    assert data["chats"] == []
    assert [e["source"] for e in data["errors"]] == ["library"]
    assert any(n.level is Level.ERROR and n.title == "Library" for n in env.notifier.notes)
    assert env.task is not None
    assert not env.task.done()
    await env.stop()


async def test_library_fixed_later_starts_the_workers_and_clears_the_error(
    tmp_path: Path,
) -> None:
    env = make_env(tmp_path, library="not = [valid", chats={"@a": (A, "Alpha")})
    env.start()
    await env.wait_running()
    assert [e["source"] for e in (await env.status() or {})["errors"]] == ["library"]

    env.write_library(library_text(("@a", "Alpha", True)))
    await env.wait_live(A)
    data = await env.status()
    await env.stop()

    assert data is not None
    assert data["errors"] == []


async def test_missing_library_file_is_an_empty_library_without_errors(tmp_path: Path) -> None:
    env = make_env(tmp_path, library=None)
    env.start()

    await env.wait_running()
    data = await env.status()
    await env.stop()

    assert data is not None
    assert data["chats"] == []
    assert data["errors"] == []


async def test_hot_reload_adds_disables_reenables_and_removes_chats(tmp_path: Path) -> None:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
        messages={A: 3, B: 3},
    )
    env.start()
    await env.wait_live(A)

    env.write_library(library_text(("@a", "Alpha", True), ("@b", "Beta", True)))
    await env.wait_live(A, B)
    assert set(await env.chats()) == {A, B}

    env.write_library(library_text(("@a", "Alpha", True), ("@b", "Beta", False)))
    await env.until_async(lambda: _only(env, {A}))
    assert folder_ids(env) == sorted([A, B])

    env.write_library(library_text(("@a", "Alpha", True), ("@b", "Beta", True)))
    await env.wait_live(A, B)
    state_b = load_state(env.root / chat_folder_name("Beta", B))
    assert state_b is not None
    assert state_b.last_id == 3

    env.write_library(library_text(("@a", "Alpha", True)))
    await env.until_async(lambda: _only(env, {A}))
    await env.stop()

    assert folder_ids(env) == sorted([A, B])


async def _only(env: Env, expected: set[int]) -> bool:
    return set(await env.chats()) == expected


async def test_hot_reload_does_not_disturb_untouched_chats(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()
    await env.wait_live(A, B)
    calls_before = env.gateway.count("newest_id")

    env.write_library(library_text(("@a", "Alpha", True), ("@b", "Beta", True), ("@c", "G", False)))
    await env.clock.advance(30)
    await env.stop()

    assert env.gateway.count("newest_id") == calls_before


async def test_session_revoked_in_a_worker_ends_the_run_and_notifies(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.gateway.fail["newest_id"] = [SessionRevoked("gone")]
    task = env.start()

    async def finished() -> bool:
        return task.done()

    await env.until_async(finished)

    assert task.exception() is None
    assert any(n.level is Level.ERROR and "revoked" in n.title.lower() for n in env.notifier.notes)
    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)


async def test_session_revoked_while_resolving_propagates_and_releases_everything(
    tmp_path: Path,
) -> None:
    env = two_chats(tmp_path)
    env.gateway.fail["resolve"] = [SessionRevoked("gone")]

    with pytest.raises(SessionRevoked):
        await env.app.run()

    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)


async def test_connect_failure_propagates_and_releases_the_lock(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.gateway.fail["connect"] = [SessionRevoked("no session")]

    with pytest.raises(SessionRevoked):
        await env.app.run()

    assert not service_running(env.ctx.paths.lock_file)
    assert env.gateway.handlers == []


async def test_shutdown_from_another_thread_flushes_buffered_messages(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    task = env.start()
    await env.wait_live(A, B)
    await env.gateway.fire(NewMessageEvent(msg(500, chat_id=A, date=NOW, text="late news")))
    await asyncio.sleep(0.05)

    worker = threading.Thread(target=env.app.request_shutdown)
    worker.start()
    await asyncio.wait_for(task, 15)
    worker.join()

    lines = [
        json.loads(line)
        for path in (env.root / chat_folder_name("Alpha", A)).glob("*.jsonl")
        for line in path.read_text("utf-8").splitlines()
    ]
    assert 500 in {line.get("msg_id") for line in lines}
    state = load_state(env.root / chat_folder_name("Alpha", A))
    assert state is not None
    assert state.last_id == 500


async def test_shutdown_requested_before_run_ends_the_run_promptly(tmp_path: Path) -> None:
    env = two_chats(tmp_path)

    env.app.request_shutdown()
    await asyncio.wait_for(env.app.run(), 15)

    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)


async def test_request_shutdown_after_the_loop_is_gone_does_not_raise(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()
    await env.wait_live(A, B)
    await env.stop()

    env.app.request_shutdown()
    env.app.request_shutdown()


async def test_events_for_untracked_chats_are_dropped_and_tracked_ones_stored(
    tmp_path: Path,
) -> None:
    env = two_chats(tmp_path)
    env.start()
    await env.wait_live(A, B)

    await env.gateway.fire(NewMessageEvent(msg(9, chat_id=-777, date=NOW)))
    await env.gateway.fire(NewMessageEvent(msg(900, chat_id=B, date=NOW)))
    await env.stop()

    assert folder_ids(env) == sorted([A, B])
    state = load_state(env.root / chat_folder_name("Beta", B))
    assert state is not None
    assert state.last_id == 900


async def test_service_state_is_reported_while_running(tmp_path: Path) -> None:
    env = two_chats(tmp_path)
    env.start()
    await env.wait_live(A, B)

    data = await env.status()
    await env.stop()

    assert data is not None
    assert data["service"] == "running"
    assert data["disk"]["low_watermark_gb"] == 15
    assert set(data) == {
        "updated_at",
        "service",
        "disk",
        "total_bytes",
        "backfill",
        "chats",
        "errors",
    }


async def _boom(*args: object, **kwargs: object) -> None:
    raise RuntimeError("cannot schedule new futures after shutdown")


@pytest.mark.parametrize(
    ("owner", "method"),
    [
        (StatusWriter, "write"),
        (Supervisor, "stop_all"),
        (ChatImportApp, "_stop_runtime"),
    ],
)
async def test_a_failing_shutdown_step_still_disconnects_and_frees_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: type, method: str
) -> None:
    env = two_chats(tmp_path)
    task = env.start()
    await env.wait_live(A, B)
    monkeypatch.setattr(owner, method, _boom)

    env.app.request_shutdown()
    await asyncio.wait_for(task, 10)

    assert env.gateway.calls[-1] == ("disconnect", ())
    assert not service_running(env.ctx.paths.lock_file)
