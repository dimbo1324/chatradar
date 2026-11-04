from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.fakes import CHAT_ID
from tests.unit.interfaces.test_cli_commands import invoke

if TYPE_CHECKING:
    from filelock import FileLock

    from tests.unit.interfaces.conftest import Env, SentCommands


def test_export_all_builds_offline_with_config_defaults(env: Env) -> None:
    env.make_chat(CHAT_ID, "Example group", range(1, 4))
    result = invoke(env, "export-all")
    target = env.ctx.root / "_exports" / "all_chats.json"
    assert result.exit_code == 0
    assert f"Wrote {target} (3 records)" in result.output
    data = json.loads(target.read_text(encoding="utf-8"))
    assert [item["msg_id"] for item in data] == [1, 2, 3]
    assert data[0]["sender_name"] is None


def test_export_all_options_override_the_config(env: Env) -> None:
    env.make_chat(CHAT_ID, "Example group", range(1, 3))
    result = invoke(env, "export-all", "--format", "jsonl", "--names")
    assert result.exit_code == 0
    target = env.ctx.root / "_exports" / "all_chats.jsonl"
    assert len(target.read_text(encoding="utf-8").splitlines()) == 2


def test_export_all_rejects_an_unknown_format(env: Env) -> None:
    result = invoke(env, "export-all", "--format", "xml")
    assert result.exit_code == 2
    assert "--format must be one of" in result.output


def test_export_all_goes_through_a_running_service(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    result = invoke(env, "export-all", "--format", "json", "--no-names")
    assert result.exit_code == 0
    assert sent.calls == [("export_all", {"format": "json", "names": False})]
    assert "Combined file built" in result.output
