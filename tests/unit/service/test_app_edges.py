from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from chatimport.ports import NewMessageEvent, ResolvedChat, ResolveStatus
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import STATE_FILE, load_state
from tests.fakes import NOW, msg
from tests.unit.service.harness import Env, library_text, make_env
from tests.unit.service.helpers import StubController

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

A, B, C = -1001, -1002, -1003


def same_chat_twice(tmp_path: Path) -> Env:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True), ("https://t.me/a", "Alias", True)),
        chats={"@a": (A, "Alpha chat")},
    )
    env.gateway.refs["https://t.me/a"] = ResolvedChat(
        "https://t.me/a", ResolveStatus.FOUND, chat_id=A, title="Alpha chat", username="a"
    )
    return env


async def test_two_entries_for_one_chat_start_one_worker(tmp_path: Path) -> None:
    env = same_chat_twice(tmp_path)
    env.start()

    await env.wait_live(A)
    chats = await env.chats()
    await env.stop()

    assert list(chats) == [A]


async def test_removing_one_of_two_entries_for_a_chat_keeps_the_chat_running(
    tmp_path: Path,
) -> None:
    env = same_chat_twice(tmp_path)
    env.start()
    await env.wait_live(A)

    env.write_library(library_text(("@a", "Alpha", True)))
    await env.clock.advance(30)
    chats = await env.chats()
    await env.stop()

    assert list(chats) == [A]


async def test_removing_both_entries_for_a_chat_stops_it_once(tmp_path: Path) -> None:
    env = same_chat_twice(tmp_path)
    env.start()
    await env.wait_live(A)

    env.write_library("")
    await env.until_async(lambda: _gone(env))
    await env.stop()


async def _gone(env: Env) -> bool:
    return not await env.chats()


async def test_library_breaking_while_running_keeps_chats_and_reports_then_clears(
    tmp_path: Path,
) -> None:
    env = make_env(
        tmp_path, library=library_text(("@a", "Alpha", True)), chats={"@a": (A, "Alpha chat")}
    )
    env.start()
    await env.wait_live(A)

    env.write_library("[[chat]\nref = ")
    await env.clock.advance(11)
    broken = await env.status()
    env.write_library(library_text(("@a", "Alpha", True), ("@z", None, False)))
    await env.clock.advance(11)
    fixed = await env.status()
    await env.stop()

    assert broken is not None
    assert [e["source"] for e in broken["errors"]] == ["library"]
    assert [c["chat_id"] for c in broken["chats"]] == [A]
    assert fixed is not None
    assert fixed["errors"] == []


async def test_entry_removed_before_its_staggered_launch_never_starts(tmp_path: Path) -> None:
    env = make_env(
        tmp_path,
        config={"backfill": {"pause_between_chats_sec": 100}},
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
    )
    env.start()
    await env.wait_running()
    await env.clock.advance(1)

    env.write_library(library_text(("@a", "Alpha", True)))
    await env.clock.advance(11)
    await env.clock.advance(200)
    await env.stop()

    assert not (env.root / chat_folder_name("Beta", B)).exists()
    assert load_state(env.root / chat_folder_name("Alpha", A)) is not None


async def test_only_the_first_fresh_chat_starts_immediately_the_rest_are_staggered(
    tmp_path: Path,
) -> None:
    env = make_env(
        tmp_path,
        config={"backfill": {"pause_between_chats_sec": 100}},
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True), ("@c", "Gamma", True)),
        chats={"@a": (A, "A"), "@b": (B, "B"), "@c": (C, "C")},
    )
    env.start()
    await env.wait_running()
    await env.clock.advance(1)
    started_early = len(env.gateway.chats) and env.gateway.count("newest_id")

    await env.clock.advance(100)
    after_one_pause = env.gateway.count("newest_id")
    await env.clock.advance(100)
    after_two = env.gateway.count("newest_id")
    await env.stop()

    assert started_early == 1
    assert after_one_pause == 2
    assert after_two == 3


async def test_events_arriving_after_the_runtime_is_gone_are_dropped_quietly(
    tmp_path: Path,
) -> None:
    env = make_env(
        tmp_path, library=library_text(("@a", "Alpha", True)), chats={"@a": (A, "Alpha chat")}
    )
    env.start()
    await env.wait_live(A)
    await env.stop()

    await env.gateway.fire(NewMessageEvent(msg(99, chat_id=A, date=NOW)))

    state = load_state(env.root / chat_folder_name("Alpha", A))
    assert state is not None
    assert state.last_id == 3


async def test_startup_recheck_marks_never_checked_chats(tmp_path: Path) -> None:
    env = make_env(
        tmp_path,
        config={"recheck": {"enabled": True, "pause_between_chats_sec": 0}},
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "Alpha chat")},
    )
    env.start()

    def checked() -> bool:
        state = load_state(env.root / chat_folder_name("Alpha", A))
        return state is not None and state.last_recheck_at is not None

    await env.until(checked)
    await env.stop()


async def test_a_worker_that_fails_to_stop_does_not_block_shutdown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = make_env(
        tmp_path, library=library_text(("@a", "Alpha", True)), chats={"@a": (A, "Alpha chat")}
    )
    env.start()
    await env.wait_live(A)

    class Broken(StubController):
        async def stop(self) -> None:
            raise RuntimeError("stuck")

    env.app._runtime().registry.add(Broken(-5))  # pyright: ignore[reportPrivateUsage]
    with caplog.at_level(logging.ERROR, logger="chatimport.app"):
        await env.stop()

    assert "a worker did not stop cleanly: RuntimeError" in caplog.text
    state = load_state(env.root / chat_folder_name("Alpha", A))
    assert state is not None


async def test_deeper_skips_chats_whose_state_file_vanished(tmp_path: Path) -> None:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
    )
    env.start()
    await env.wait_live(A, B)
    (env.root / chat_folder_name("Alpha", A) / STATE_FILE).unlink()

    result = await env.run_command("deeper")
    await env.stop()

    assert result.ok
    assert result.data == {"chats": 1}
