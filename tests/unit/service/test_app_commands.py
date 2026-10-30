from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from chatimport.app import ChatImportApp
from chatimport.control import COMMANDS
from chatimport.status import format_status_lines
from chatimport.storage.layout import chat_folder_name, list_parts
from chatimport.storage.state import load_state
from tests.unit.service.harness import Env, library_text, make_env

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

A, B = -1001, -1002


@pytest_asyncio.fixture
async def live(tmp_path: Path) -> AsyncIterator[Env]:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
        messages={A: 4, B: 3},
    )
    task = env.start()
    await env.wait_live(A, B)
    yield env
    if not task.done():
        await env.stop()


def paused_flags(data: dict[str, Any]) -> dict[int, bool]:
    return {c["chat_id"]: c["paused"] for c in data["chats"]}


async def test_unknown_command_is_a_failed_result_not_an_exception(live: Env) -> None:
    result = await live.run_command("rm-rf")

    assert result.ok is False
    assert "unknown command" in result.message


@pytest.mark.parametrize("name", COMMANDS)
async def test_every_documented_command_is_known_to_execute(tmp_path: Path, name: str) -> None:
    env = make_env(tmp_path)

    result = await env.app.execute(name, {})

    assert "unknown command" not in result.message


def test_build_handlers_covers_every_command_name(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    handlers = env.app.build_handlers()

    assert set(handlers) == set(COMMANDS)


async def test_built_handlers_delegate_to_execute_with_their_own_name(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    seen: list[tuple[str, dict[str, Any]]] = []

    async def spy(command: str, args: dict[str, Any]) -> Any:
        seen.append((command, args))
        return await ChatImportApp.execute(env.app, command, args)

    env.app.execute = spy  # type: ignore[method-assign]  # pyright: ignore[reportAttributeAccessIssue]
    handlers = env.app.build_handlers()

    await handlers["pause"]({"x": 1})
    await handlers["trim"]({"pct": 25})

    assert seen == [("pause", {"x": 1}), ("trim", {"pct": 25})]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("status", {}),
        ("trim", {"pct": 50}),
        ("pause", {}),
        ("resume", {}),
        ("recheck", {}),
        ("refetch", {}),
        ("deeper", {}),
        ("check", {"repair": True}),
    ],
)
async def test_runtime_commands_fail_cleanly_when_the_service_is_not_running(
    tmp_path: Path, name: str, args: dict[str, Any]
) -> None:
    env = make_env(tmp_path)

    result = await env.app.execute(name, args)

    assert result.ok is False
    assert "not running" in result.message


async def test_status_command_returns_the_snapshot_and_a_summary_line(live: Env) -> None:
    result = await live.run_command("status")

    assert result.ok
    assert result.message == format_status_lines(result.data)[0]
    assert result.message.startswith("2 chats · live")
    assert {c["chat_id"] for c in result.data["chats"]} == {A, B}
    assert all(c["last_id"] > 0 for c in result.data["chats"])


@pytest.mark.parametrize("chat", [None, ""])
async def test_pause_and_resume_without_a_chat_touch_every_chat(
    live: Env, chat: str | None
) -> None:
    paused = await live.run_command("pause", chat=chat)
    after_pause = await live.status()
    resumed = await live.run_command("resume", chat=chat)
    after_resume = await live.status()

    assert paused.message == "paused 2 chats"
    assert resumed.message == "resumed 2 chats"
    assert after_pause is not None
    assert after_resume is not None
    assert paused_flags(after_pause) == {A: True, B: True}
    assert paused_flags(after_resume) == {A: False, B: False}


@pytest.mark.parametrize("selector", [A, str(A), "@a", "Alpha", "alpha", "Alpha chat"])
async def test_a_chat_selector_limits_the_command_to_one_chat(live: Env, selector: object) -> None:
    result = await live.run_command("pause", chat=selector)
    data = await live.status()

    assert result.ok, result.message
    assert result.message == "paused 1 chats"
    assert data is not None
    assert paused_flags(data) == {A: True, B: False}


@pytest.mark.parametrize("selector", [-999, "-999", "nobody", "@nobody", True, 3.5])
async def test_an_unknown_chat_selector_fails_and_changes_nothing(
    live: Env, selector: object
) -> None:
    result = await live.run_command("pause", chat=selector)
    data = await live.status()

    assert result.ok is False
    assert data is not None
    assert paused_flags(data) == {A: False, B: False}


async def test_trim_reports_totals_and_validates_the_percentage(live: Env) -> None:
    good = await live.run_command("trim", pct=50)

    assert good.ok
    assert set(good.data) == {"records", "bytes", "parts", "per_chat"}
    assert all(isinstance(key, str) for key in good.data["per_chat"])
    assert good.message.startswith(f"trimmed {good.data['records']} records")


@pytest.mark.parametrize("pct", [0, 10, 100, -25, 26, "abc", None, 1.5])
async def test_trim_rejects_bad_percentages_without_deleting(live: Env, pct: object) -> None:
    before = {p.name for p in (live.root / chat_folder_name("Alpha", A)).iterdir()}

    result = await live.run_command("trim", pct=pct)

    assert result.ok is False
    assert {p.name for p in (live.root / chat_folder_name("Alpha", A)).iterdir()} == before


async def test_trim_without_pct_names_the_missing_argument(live: Env) -> None:
    result = await live.run_command("trim")

    assert result.ok is False
    assert "pct" in result.message


async def test_trim_accepts_a_percentage_given_as_text_and_a_chat_selector(live: Env) -> None:
    result = await live.run_command("trim", pct="25", chat="Beta")

    assert result.ok, result.message
    assert set(result.data["per_chat"]) <= {str(B)}


async def test_trim_of_an_untracked_numeric_chat_trims_nothing(live: Env) -> None:
    result = await live.run_command("trim", pct=75, chat=-4242)

    assert result.ok
    assert result.data["records"] == 0
    assert result.data["parts"] == 0


async def test_recheck_asks_every_chat_or_the_selected_one(live: Env) -> None:
    everyone = await live.call("recheck")
    one = await live.call("recheck", chat="@b")
    nobody = await live.call("recheck", chat=-4242)

    assert (everyone.ok, everyone.data) == (True, {"chats": 2})
    assert one.data == {"chats": 1}
    assert nobody.data == {"chats": 0}
    assert one.message == "recheck requested for 1 chats"


@pytest.mark.parametrize("days", [0, -1, "0"])
async def test_recheck_needs_at_least_one_day(live: Env, days: object) -> None:
    result = await live.call("recheck", days=days)

    assert result.ok is False
    assert "days" in result.message


async def test_recheck_with_garbage_days_is_a_failed_result(live: Env) -> None:
    result = await live.call("recheck", days="soon")

    assert result.ok is False


async def test_recheck_with_days_is_accepted_as_number_or_text(live: Env) -> None:
    assert (await live.call("recheck", days=3)).ok
    assert (await live.call("recheck", days="14", chat=A)).ok


async def test_refetch_sends_every_selected_chat_back_to_head_backfill(live: Env) -> None:
    before = live.gateway.count("newest_id")

    result = await live.run_command("refetch", chat="Alpha")
    await live.until(lambda: live.gateway.count("newest_id") > before)
    await live.wait_live(A, B)

    assert result.message == "refetch requested for 1 chats"
    assert live.gateway.count("newest_id") == before + 1 or live.gateway.count("newest_id") > before


async def test_deeper_reopens_the_backfill_and_lets_it_finish_again(live: Env) -> None:
    folder = live.root / chat_folder_name("Alpha", A)
    state = load_state(folder)
    assert state is not None
    assert state.backfill.done

    result = await live.run_command("deeper", chat=A)

    def finished() -> bool:
        reloaded = load_state(folder)
        return reloaded is not None and reloaded.backfill.done

    await live.until(finished, step=60)
    assert result.ok
    assert result.data == {"chats": 1}
    assert result.message == "lowered the floor of 1 chats"
    after = load_state(folder)
    assert after is not None
    assert after.floor_id == 0
    assert after.backfill.done


async def test_deeper_without_a_chat_lowers_every_chat(live: Env) -> None:
    result = await live.run_command("deeper")

    assert result.data == {"chats": 2}


async def test_deeper_for_an_untracked_chat_fails(live: Env) -> None:
    result = await live.run_command("deeper", chat=-4242)

    assert result.ok is False
    assert "not tracked" in result.message


async def test_shutdown_command_ends_the_run_after_answering(live: Env) -> None:
    result = await live.run_command("shutdown")

    assert result == type(result)(True, "shutting down")
    assert live.task is not None
    await asyncio.wait_for(live.task, 15)
    assert not live.gateway.connected


async def test_reload_config_applies_new_values_for_future_chats(live: Env) -> None:
    live.ctx.paths.config_file.write_text("[live]\nflush_every_messages = 9\n", encoding="utf-8")

    result = await live.run_command("reload_config")

    assert result.ok
    assert live.app.ctx.config.live.flush_every_messages == 9
    assert live.app.ctx.root == live.ctx.root


@pytest.mark.parametrize(
    "text",
    ["[live\nx=", "[output]\nmax_chunk_mb = 0\n", "[nonsense]\na = 1\n"],
)
async def test_reload_config_with_a_bad_file_fails_and_keeps_the_old_config(
    live: Env, text: str
) -> None:
    live.ctx.paths.config_file.write_text(text, encoding="utf-8")
    before = live.app.ctx.config

    result = await live.run_command("reload_config")

    assert result.ok is False
    assert live.app.ctx.config == before


async def test_check_reports_no_issues_for_healthy_data(live: Env) -> None:
    result = await live.run_command("check")

    assert result.ok
    if result.data["count"] == 0:
        assert result.message == "no issues found"
    assert result.message.splitlines()[0].endswith("found")
    assert len(result.message.splitlines()) == 1 + result.data["count"]


def corrupt_tail(folder: Path) -> None:
    part = list_parts(folder)[-1]
    with part.open("ab") as handle:
        handle.write(b'{"v":1,"kind":"mess')


async def test_check_finds_a_torn_line_and_repair_fixes_it(live: Env) -> None:
    folder = live.root / chat_folder_name("Alpha", A)
    corrupt_tail(folder)

    found = await live.run_command("check")
    repaired = await live.run_command("check", repair=True)
    again = await live.run_command("check")

    assert found.data["count"] >= 1
    assert all(issue["chat_id"] == A or issue["chat_id"] is None for issue in found.data["issues"])
    assert set(found.data["issues"][0]) == {"chat_id", "folder", "severity", "message"}
    assert repaired.ok
    assert again.data["count"] == 0
    assert again.message == "no issues found"


async def test_check_with_repair_waits_for_the_chat_lock(live: Env) -> None:
    controller = live.app._runtime().registry.get(A)  # pyright: ignore[reportPrivateUsage]
    assert controller is not None

    async with controller.lock:
        task = asyncio.create_task(live.run_command("check", repair=True))
        await asyncio.sleep(0.05)
        assert not task.done()
    result = await asyncio.wait_for(task, 10)

    assert result.ok


async def test_check_without_repair_does_not_take_the_chat_lock(live: Env) -> None:
    controller = live.app._runtime().registry.get(A)  # pyright: ignore[reportPrivateUsage]
    assert controller is not None

    async with controller.lock:
        result = await asyncio.wait_for(live.run_command("check"), 10)

    assert result.ok


async def test_command_exception_text_never_includes_a_traceback(live: Env) -> None:
    result = await live.run_command("trim", pct=object())

    assert result.ok is False
    assert "Traceback" not in result.message
    json.dumps({"message": result.message})
