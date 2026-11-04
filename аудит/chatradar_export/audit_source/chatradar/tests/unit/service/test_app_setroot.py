from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from chatimport.config import load_config
from chatimport.ports import ResolvedChat, ResolveStatus
from chatimport.storage.layout import chat_folder_name, iter_chat_folders
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
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True), ("@gone", None, True)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
        messages={A: 4, B: 3},
    )
    env.gateway.refs["@gone"] = ResolvedChat("@gone", ResolveStatus.NOT_FOUND)
    task = env.start()
    await env.wait_live(A, B)
    yield env
    if not task.done():
        await env.stop()


def stored_ids(root: Path, chat_id: int) -> list[int]:
    ids: list[int] = []
    folder = root / chat_folder_name("Alpha" if chat_id == A else "Beta", chat_id)
    for part in sorted(folder.glob("*.jsonl")):
        for line in part.read_text("utf-8").splitlines():
            record: dict[str, Any] = json.loads(line)
            if record["kind"] == "message":
                ids.append(record["msg_id"])
    return ids


async def test_same_folder_is_reported_unchanged_and_nothing_restarts(live: Env) -> None:
    calls = live.gateway.count("newest_id")

    result = await live.run_command("set_root", path=str(live.root))

    assert result.ok
    assert result.message == "the folder is unchanged"
    assert live.gateway.count("newest_id") == calls


@pytest.mark.parametrize("path", [None, "", "   ", 5, ["x"]])
async def test_missing_or_blank_path_is_rejected(live: Env, path: object) -> None:
    result = await live.run_command("set_root", path=path)

    assert result.ok is False
    assert "path is required" in result.message


async def test_a_path_inside_the_current_folder_is_refused_and_the_service_keeps_running(
    live: Env,
) -> None:
    result = await live.run_command("set_root", path=str(live.root / "nested"))

    assert result.ok is False
    assert "inside" in result.message
    assert live.app.ctx.root == live.root
    assert set(await live.chats()) == {A, B}


async def test_without_move_chats_are_fetched_again_into_the_new_folder(
    live: Env, tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere"

    result = await live.run_command("set_root", path=str(target))
    await live.wait_live(A, B)

    new_root = target / "ChatImport"
    assert result.ok, result.message
    assert result.data == {"path": str(new_root)}
    assert "data was not moved" in result.message
    assert live.app.ctx.root == new_root
    assert stored_ids(new_root, A) == [1, 2, 3, 4]
    assert stored_ids(new_root, B) == [1, 2, 3]
    assert stored_ids(live.root, A) == [1, 2, 3, 4]
    assert load_config(live.ctx.paths.config_file).output.root_dir == str(new_root)


async def test_with_move_the_data_follows_and_nothing_is_duplicated_or_lost(
    live: Env, tmp_path: Path
) -> None:
    old_root = live.root
    new_root = tmp_path / "moved" / "ChatImport"
    state_before = load_state(old_root / chat_folder_name("Alpha", A))
    assert state_before is not None

    result = await live.run_command("set_root", path=str(tmp_path / "moved"), move=True)
    await live.wait_live(A, B)

    assert result.ok, result.message
    assert "data was not moved" not in result.message
    assert not old_root.exists()
    assert stored_ids(new_root, A) == [1, 2, 3, 4]
    assert stored_ids(new_root, B) == [1, 2, 3]
    state_after = load_state(new_root / chat_folder_name("Alpha", A))
    assert state_after is not None
    assert state_after.last_id == state_before.last_id
    assert sorted(f.name for f in iter_chat_folders(new_root)) == sorted(
        [chat_folder_name("Alpha", A), chat_folder_name("Beta", B)]
    )


async def test_a_path_that_already_ends_with_the_app_folder_is_used_as_is(
    live: Env, tmp_path: Path
) -> None:
    target = tmp_path / "x" / "chatimport"

    result = await live.run_command("set_root", path=str(target), move=True)

    assert result.ok, result.message
    assert live.app.ctx.root == target


async def test_environment_override_warning_depends_on_the_variable(
    live: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_env = await live.run_command("set_root", path=str(tmp_path / "one"), move=True)
    monkeypatch.delenv("CHATIMPORT_ROOT")
    without_env = await live.run_command("set_root", path=str(tmp_path / "two"), move=True)

    assert "CHATIMPORT_ROOT is set" in with_env.message
    assert "CHATIMPORT_ROOT" not in without_env.message


async def test_failed_move_restarts_the_service_on_the_old_root(
    live: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_move(old: Path, new: Path, *, move: bool) -> None:
        raise OSError("disk unplugged")

    monkeypatch.setattr("chatimport.app.move_root", failing_move)
    config_before = live.ctx.paths.config_file.exists()

    result = await live.run_command("set_root", path=str(tmp_path / "bad"), move=True)
    await live.wait_live(A, B)

    assert result.ok is False
    assert "disk unplugged" in result.message
    assert live.app.ctx.root == live.root
    assert live.ctx.paths.config_file.exists() == config_before
    assert stored_ids(live.root, A) == [1, 2, 3, 4]
    assert set(await live.chats()) == {A, B}


async def test_failed_config_update_still_adopts_the_new_root_and_says_so(
    live: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_write(path: Path, root: Path) -> None:
        raise OSError("read-only config")

    monkeypatch.setattr("chatimport.app.set_output_root", failing_write)

    result = await live.run_command("set_root", path=str(tmp_path / "new"), move=True)
    await live.wait_live(A, B)

    new_root = tmp_path / "new" / "ChatImport"
    assert result.ok is False
    assert "data is now in" in result.message
    assert str(new_root) in result.message
    assert "read-only config" in result.message
    assert live.app.ctx.root == new_root
    assert stored_ids(new_root, A) == [1, 2, 3, 4]


async def test_unresolved_library_errors_survive_a_root_change(live: Env, tmp_path: Path) -> None:
    before = await live.status()
    assert before is not None
    assert [e["source"] for e in before["errors"]] == ["resolve:@gone"]

    await live.run_command("set_root", path=str(tmp_path / "again"), move=True)
    await live.wait_live(A, B)
    after = await live.status()

    assert after is not None
    assert [e["source"] for e in after["errors"]] == ["resolve:@gone"]
    assert after["disk"]["path"] == str(tmp_path / "again" / "ChatImport")


async def test_hot_reload_keeps_working_after_a_root_change(live: Env, tmp_path: Path) -> None:
    live.gateway.refs["@c"] = ResolvedChat(
        "@c", ResolveStatus.FOUND, chat_id=-1003, title="Gamma", username="c"
    )
    live.gateway.add_chat(-1003, range(1, 3))
    await live.run_command("set_root", path=str(tmp_path / "again"), move=True)
    await live.wait_live(A, B)

    live.write_library(
        library_text(("@a", "Alpha", True), ("@b", "Beta", True), ("@c", "Gamma", True))
    )
    await live.wait_live(A, B, -1003)

    assert (tmp_path / "again" / "ChatImport" / chat_folder_name("Gamma", -1003)).is_dir()


async def test_shutdown_after_a_root_change_writes_the_final_status_in_the_new_root(
    live: Env, tmp_path: Path
) -> None:
    await live.run_command("set_root", path=str(tmp_path / "again"), move=True)
    await live.wait_live(A, B)

    await live.stop()

    data = json.loads((tmp_path / "again" / "ChatImport" / "_status.json").read_text("utf-8"))
    assert data["service"] == "stopped"
