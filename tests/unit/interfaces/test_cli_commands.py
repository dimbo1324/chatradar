# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import app as app_module
from chatimport import cli
from chatimport.control import AlreadyRunning, CommandResult
from chatimport.ports import ChatImportError, DialogInfo, ResolvedChat, ResolveStatus
from tests.fakes import CHAT_ID, FakeGateway

if TYPE_CHECKING:
    from pathlib import Path

    from filelock import FileLock
    from typer.testing import Result

    from tests.unit.interfaces.conftest import Env, SentCommands


def invoke(env: Env, *args: str, input_text: str | None = None) -> Result:
    return env.runner.invoke(cli.app, list(args), input=input_text)


def assert_clean_failure(result: Result, code: int = 1) -> None:
    assert result.exit_code == code
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, AlreadyRunning | ChatImportError | TimeoutError)


def configure_without_credentials(env: Env) -> None:
    env.ctx.paths.config_file.write_text("", encoding="utf-8")


# ----------------------------------------------------------------------------- login


@pytest.fixture
def login_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from chatimport.telegram import client

    calls: list[dict[str, Any]] = []

    async def fake_login(config: Any, session_path: Path, **prompts: Any) -> str:
        calls.append({"session": session_path, "phone": prompts["prompt_phone"]()})
        prompts["prompt_code"]()
        prompts["prompt_password"]()
        return "@owner"

    monkeypatch.setattr(client, "login", fake_login)
    return calls


def test_login_reports_the_account_and_never_echoes_secrets(
    env: Env, login_calls: list[dict[str, Any]]
) -> None:
    result = invoke(env, "login", input_text="+59899123456\n13579\nhunter2-pass\n")

    assert result.exit_code == 0
    assert "Logged in as @owner" in result.output
    assert "hunter2-pass" not in result.output
    assert login_calls[0]["session"] == env.ctx.paths.session_file
    final_line = result.output.strip().splitlines()[-1]
    assert "+59899123456" not in final_line
    assert "13579" not in final_line
    assert env.lock_is_free()


def test_login_without_credentials_exits_2_and_does_not_start_the_client(
    env: Env, login_calls: list[dict[str, Any]]
) -> None:
    configure_without_credentials(env)

    result = invoke(env, "login")

    assert_clean_failure(result, 2)
    assert "api_id" in result.output
    assert login_calls == []


def test_login_failure_is_reported_without_traceback_and_releases_the_lock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport.telegram import client

    async def failing(*args: Any, **kwargs: Any) -> str:
        raise ChatImportError("session was revoked")

    monkeypatch.setattr(client, "login", failing)

    result = invoke(env, "login")

    assert_clean_failure(result)
    assert "session was revoked" in result.output
    assert env.lock_is_free()


def test_login_refuses_while_the_service_holds_the_instance_lock(
    env: Env, running_service: FileLock, login_calls: list[dict[str, Any]]
) -> None:
    result = invoke(env, "login")

    assert_clean_failure(result)
    assert "already running" in result.output
    assert login_calls == []


def test_keyboard_interrupt_exits_1_quietly_and_releases_the_lock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport.telegram import client

    async def interrupted(*args: Any, **kwargs: Any) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(client, "login", interrupted)

    result = invoke(env, "login")

    assert result.exit_code == 1
    assert "interrupted" in result.output
    assert env.lock_is_free()


def test_unexpected_exception_is_not_swallowed_but_still_releases_the_lock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport.telegram import client

    async def broken(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("bug")

    monkeypatch.setattr(client, "login", broken)

    result = invoke(env, "login")

    assert isinstance(result.exception, RuntimeError)
    assert env.lock_is_free()


def test_broken_config_toml_is_a_clean_error(env: Env) -> None:
    env.ctx.paths.config_file.write_text("[telegram\n", encoding="utf-8")

    result = invoke(env, "status")

    assert_clean_failure(result)
    assert "config.toml" in result.output


# ----------------------------------------------------------------------------- dialogs


def patch_gateway(monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway) -> None:
    def build(ctx: object, clock: object) -> FakeGateway:
        return gateway

    monkeypatch.setattr(app_module, "build_gateway", build)


def test_dialogs_prints_an_aligned_table(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = FakeGateway(
        dialogs=[
            DialogInfo(-1001, "Short", "short", "https://t.me/short", "channel"),
            DialogInfo(-1002, "A much longer title", None, None, "supergroup"),
        ]
    )
    patch_gateway(monkeypatch, gateway)

    result = invoke(env, "dialogs")

    lines = result.output.splitlines()
    assert result.exit_code == 0
    assert lines[0].split() == ["CHAT_ID", "KIND", "TITLE", "LINK"]
    assert lines[1].split() == ["-1001", "channel", "Short", "https://t.me/short"]
    assert lines[2].split() == ["-1002", "supergroup", "A", "much", "longer", "title"]
    assert lines[1].index("Short") == lines[2].index("A much")
    assert all(line == line.rstrip() for line in lines)
    assert gateway.connected is False
    assert env.lock_is_free()


def test_dialogs_with_no_dialogs_prints_only_the_header(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_gateway(monkeypatch, FakeGateway())

    result = invoke(env, "dialogs")

    assert result.exit_code == 0
    assert result.output.split() == ["CHAT_ID", "KIND", "TITLE", "LINK"]


def test_dialogs_disconnects_the_gateway_when_listing_fails(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway(fail={"list_dialogs": [ChatImportError("flood")]})
    patch_gateway(monkeypatch, gateway)

    result = invoke(env, "dialogs")

    assert_clean_failure(result)
    assert gateway.count("disconnect") == 1
    assert env.lock_is_free()


def test_dialogs_without_credentials_exits_2(env: Env) -> None:
    configure_without_credentials(env)

    assert_clean_failure(invoke(env, "dialogs"), 2)


# ----------------------------------------------------------------------------- chats list


def test_chats_list_with_an_empty_library_explains_how_to_add(env: Env) -> None:
    result = invoke(env, "chats", "list")

    assert result.exit_code == 0
    assert "library is empty" in result.output
    assert "chats add" in result.output


def test_chats_list_works_without_credentials_when_the_library_is_empty(env: Env) -> None:
    configure_without_credentials(env)

    assert invoke(env, "chats", "list").exit_code == 0


def test_chats_list_shows_status_title_and_stored_record_count(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.write_library(
        '[[chat]]\nref = "@found"\nname = "Found"\n\n[[chat]]\nref = "@missing"\n'
        '\n[[chat]]\nref = "@private"\n'
    )
    env.make_chat(CHAT_ID, "Found chat", range(1, 8))
    gateway = FakeGateway(
        refs={
            "@found": ResolvedChat("@found", ResolveStatus.FOUND, CHAT_ID, "Found chat", "found"),
            "@private": ResolvedChat("@private", ResolveStatus.FOUND, -1009, "Fresh chat"),
        }
    )
    patch_gateway(monkeypatch, gateway)

    result = invoke(env, "chats", "list")

    rows = {line.split()[0]: line for line in result.output.splitlines()[1:]}
    assert result.exit_code == 0
    assert result.output.splitlines()[0].split() == [
        "NAME",
        "REF",
        "STATUS",
        "CHAT_ID",
        "TITLE",
        "RECORDS",
    ]
    assert rows["Found"].split() == ["Found", "@found", "found", str(CHAT_ID), "Found", "chat", "7"]
    assert rows["@missing"].split() == ["@missing", "@missing", "not_found"]
    assert rows["@private"].split() == ["@private", "@private", "found", "-1009", "Fresh", "chat"]
    assert gateway.connected is False


def test_chats_list_shows_disabled_entries_as_disabled(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.write_library(
        '[[chat]]\nref = "@on"\n\n[[chat]]\nref = "@off"\nname = "Paused one"\nenabled = false\n'
    )
    patch_gateway(monkeypatch, FakeGateway())

    result = invoke(env, "chats", "list")

    assert "Paused one" in result.output
    assert "disabled" in result.output


def test_chats_list_with_a_broken_library_is_a_clean_error(env: Env) -> None:
    env.write_library("[[chat]]\nref = \n")

    result = invoke(env, "chats", "list")

    assert_clean_failure(result)
    assert "invalid TOML" in result.output


# ------------------------------ chats add / enable / disable


def test_chats_add_appends_an_entry_that_the_library_then_lists(env: Env) -> None:
    result = invoke(env, "chats", "add", "@example", "--name", "Example")

    assert result.exit_code == 0
    assert "Added @example" in result.output
    text = env.ctx.library_file.read_text(encoding="utf-8")
    assert 'ref = "@example"' in text
    assert 'name = "Example"' in text


def test_chats_add_twice_is_rejected_and_leaves_the_file_unchanged(env: Env) -> None:
    invoke(env, "chats", "add", "@example")
    before = env.ctx.library_file.read_bytes()

    result = invoke(env, "chats", "add", " @example ")

    assert_clean_failure(result)
    assert "already in the library" in result.output
    assert env.ctx.library_file.read_bytes() == before


def test_chats_add_with_a_blank_ref_is_rejected(env: Env) -> None:
    result = invoke(env, "chats", "add", "   ")

    assert_clean_failure(result)
    assert not env.ctx.library_file.exists()


def test_chats_add_escapes_quotes_in_the_name(env: Env) -> None:
    from chatimport.library import load_library

    result = invoke(env, "chats", "add", "https://t.me/x", "--name", 'He said "hi" \\ bye')

    assert result.exit_code == 0
    assert load_library(env.ctx.library_file).entries[0].name == 'He said "hi" \\ bye'


def test_chats_disable_then_enable_round_trips_by_name_and_by_ref(env: Env) -> None:
    from chatimport.library import load_library

    invoke(env, "chats", "add", "@example", "--name", "Example")

    off = invoke(env, "chats", "disable", "example")
    assert off.exit_code == 0
    assert "Disabled example" in off.output
    assert load_library(env.ctx.library_file).entries[0].enabled is False

    on = invoke(env, "chats", "enable", "@example")
    assert on.exit_code == 0
    assert "Enabled @example" in on.output
    assert load_library(env.ctx.library_file).entries[0].enabled is True


@pytest.mark.parametrize("verb", ["disable", "enable"])
def test_chats_toggle_of_an_unknown_entry_fails_cleanly(env: Env, verb: str) -> None:
    invoke(env, "chats", "add", "@example")

    result = invoke(env, "chats", verb, "@nobody")

    assert_clean_failure(result)
    assert "no library entry" in result.output


# ----------------------------------------------------------------------------- run / tray


class FakeService:
    instances: list[FakeService] = []  # noqa: RUF012

    def __init__(self, ctx: Any, *, notifier: Any) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.error: BaseException | None = None
        FakeService.instances.append(self)

    async def run(self) -> None:
        self.calls.append(("run", None))
        if self.error:
            raise self.error

    async def run_once(self, chat: str | None = None) -> None:
        self.calls.append(("run_once", chat))
        if self.error:
            raise self.error


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> type[FakeService]:
    FakeService.instances = []
    monkeypatch.setattr(app_module, "ChatImportApp", FakeService)
    return FakeService


def test_run_starts_the_service_in_continuous_mode(
    env: Env, fake_service: type[FakeService]
) -> None:
    result = invoke(env, "run")

    assert result.exit_code == 0
    assert fake_service.instances[0].calls == [("run", None)]


def test_run_once_passes_the_chat_selector(env: Env, fake_service: type[FakeService]) -> None:
    result = invoke(env, "run", "--once", "--chat", "@example")

    assert result.exit_code == 0
    assert fake_service.instances[0].calls == [("run_once", "@example")]


def test_run_once_without_chat_catches_up_everything(
    env: Env, fake_service: type[FakeService]
) -> None:
    invoke(env, "run", "--once")

    assert fake_service.instances[0].calls == [("run_once", None)]


def test_run_refuses_when_another_instance_is_running(
    env: Env, running_service: FileLock, fake_service: type[FakeService]
) -> None:
    result = invoke(env, "run")

    assert_clean_failure(result)
    assert "already running" in result.output
    assert fake_service.instances == []


def test_run_without_credentials_exits_2(env: Env, fake_service: type[FakeService]) -> None:
    configure_without_credentials(env)

    assert_clean_failure(invoke(env, "run"), 2)
    assert fake_service.instances == []


def test_run_reports_a_service_error_without_a_traceback(
    env: Env, fake_service: type[FakeService], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = fake_service.__init__

    def init(self: FakeService, ctx: Any, *, notifier: Any) -> None:
        original(self, ctx, notifier=notifier)
        self.error = ChatImportError("session revoked")

    monkeypatch.setattr(fake_service, "__init__", init)

    result = invoke(env, "run")

    assert_clean_failure(result)
    assert "session revoked" in result.output


# ----------------------------------------------------------------------------- status


def status_payload() -> dict[str, Any]:
    return {
        "updated_at": "2026-10-29T12:00:00Z",
        "service": "running",
        "disk": {"path": "C:\\", "free_gb": 41.2, "low_watermark_gb": 15},
        "total_bytes": 3 * 1024**3,
        "chats": [
            {
                "chat_id": CHAT_ID,
                "title": "Example group",
                "phase": "live",
                "last_id": 4512,
                "backfill_done": True,
                "records": 48210,
                "paused": True,
            },
            {"chat_id": -2, "title": "Other", "phase": "head_backfill", "last_id": 7},
        ],
        "errors": [{"source": "worker", "message": "boom"}],
    }


def test_status_of_a_running_service_prints_the_live_answer(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    sent.result = CommandResult(True, "", status_payload())

    result = invoke(env, "status")

    assert result.exit_code == 0
    assert sent.calls == [("status", None)]
    assert "2 chats \u00b7 live \u00b7 3.0 GB \u00b7 41.2 GB free" in result.output
    assert "error [worker]: boom" in result.output
    assert f"{CHAT_ID} Example group: live, last_id 4512, backfill done, 48210 records, paused" in (
        result.output
    )
    assert "Other: head_backfill, last_id 7, backfill in progress, 0 records" in result.output
    assert "not running" not in result.output


def test_status_of_a_stopped_service_reads_the_snapshot_and_says_stopped(env: Env) -> None:
    env.ctx.root.mkdir(parents=True)
    (env.ctx.root / "_status.json").write_text(json.dumps(status_payload()), encoding="utf-8")

    result = invoke(env, "status")

    assert result.exit_code == 0
    assert "not running (last snapshot 2026-10-29T12:00:00Z)" in result.output
    assert "2 chats \u00b7 stopped" in result.output


def test_status_of_a_stopped_service_without_snapshot_fails_cleanly(env: Env) -> None:
    result = invoke(env, "status")

    assert_clean_failure(result)
    assert "no status snapshot" in result.output


@pytest.mark.parametrize("content", ["{not json", "", "[1, 2]", "null", '"text"'])
def test_status_with_a_corrupt_snapshot_fails_cleanly(env: Env, content: str) -> None:
    env.ctx.root.mkdir(parents=True)
    (env.ctx.root / "_status.json").write_text(content, encoding="utf-8")

    result = invoke(env, "status")

    assert_clean_failure(result)
    assert not isinstance(result.exception, ValueError | TypeError)


def test_status_when_the_service_answers_with_an_error_fails_cleanly(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    sent.result = CommandResult(False, "status is unavailable")

    result = invoke(env, "status")

    assert_clean_failure(result)
    assert "status is unavailable" in result.output


def test_a_command_that_fails_without_a_message_names_the_command(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    sent.result = CommandResult(False, "")

    result = invoke(env, "status")

    assert "status failed" in result.output


def test_command_timeout_is_reported_without_a_traceback(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    sent.raises = TimeoutError("no answer to 'status' within 30 s")

    result = invoke(env, "status")

    assert_clean_failure(result)
    assert "no answer" in result.output


# ----------------------------------------------------------------------------- trim


@pytest.fixture
def offline_trim_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int | None]]:
    from chatimport import offline
    from chatimport.trim import TrimReport

    calls: list[tuple[int, int | None]] = []

    async def fake_trim(ctx: Any, pct: int, chat: int | None) -> TrimReport:
        calls.append((pct, chat))
        return TrimReport(trimmed_records=12, freed_bytes=3 * 1024 * 1024 // 2)

    monkeypatch.setattr(offline, "offline_trim", fake_trim)
    return calls


@pytest.mark.parametrize("pct", ["0", "10", "100", "-25", "26", "abc"])
def test_trim_rejects_percentages_other_than_25_50_75(
    env: Env, sent: SentCommands, offline_trim_calls: list[Any], pct: str
) -> None:
    result = invoke(env, "trim", "--yes", "--", pct)

    assert result.exit_code == 2
    assert offline_trim_calls == []
    assert sent.calls == []


@pytest.mark.parametrize("pct", [25, 50, 75])
def test_trim_offline_runs_in_process_and_reports_the_result(
    env: Env, offline_trim_calls: list[Any], pct: int
) -> None:
    result = invoke(env, "trim", str(pct), "--yes")

    assert result.exit_code == 0
    assert offline_trim_calls == [(pct, None)]
    assert "Deleted 0 parts, 12 records, freed 1.5 MB" in result.output
    assert env.lock_is_free()


def test_trim_offline_resolves_the_chat_selector_to_an_id(
    env: Env, offline_trim_calls: list[Any]
) -> None:
    env.make_chat(CHAT_ID, "Example group")

    result = invoke(env, "trim", "50", "--chat", "Example group", "--yes")

    assert result.exit_code == 0
    assert offline_trim_calls == [(50, CHAT_ID)]


def test_trim_of_an_unknown_chat_fails_cleanly_and_deletes_nothing(
    env: Env, offline_trim_calls: list[Any]
) -> None:
    result = invoke(env, "trim", "50", "--chat", "nobody", "--yes")

    assert_clean_failure(result)
    assert offline_trim_calls == []
    assert env.lock_is_free()


def test_trim_asks_for_confirmation_and_aborts_on_the_default_answer(
    env: Env, offline_trim_calls: list[Any]
) -> None:
    result = invoke(env, "trim", "50", input_text="\n")

    assert result.exit_code == 1
    assert "oldest 50%" in result.output
    assert "every chat" in result.output
    assert "aborted" in result.output
    assert offline_trim_calls == []


def test_trim_confirmation_names_the_chat(env: Env, offline_trim_calls: list[Any]) -> None:
    env.make_chat(CHAT_ID, "Example group")

    result = invoke(env, "trim", "25", "--chat", "Example group", input_text="n\n")

    assert "of Example group?" in result.output
    assert offline_trim_calls == []


@pytest.mark.parametrize("answer", ["y", "Y", "yes"])
def test_trim_proceeds_when_confirmed(env: Env, offline_trim_calls: list[Any], answer: str) -> None:
    result = invoke(env, "trim", "75", input_text=f"{answer}\n")

    assert result.exit_code == 0
    assert offline_trim_calls == [(75, None)]


def test_trim_with_a_running_service_sends_the_command_and_does_not_touch_files(
    env: Env, running_service: FileLock, sent: SentCommands, offline_trim_calls: list[Any]
) -> None:
    sent.result = CommandResult(True, "Trimmed 2 parts")

    result = invoke(env, "trim", "50", "--chat", "@example", "--yes")

    assert result.exit_code == 0
    assert sent.calls == [("trim", {"pct": 50, "chat": "@example"})]
    assert "Trimmed 2 parts" in result.output
    assert offline_trim_calls == []


def test_trim_with_a_running_service_still_asks_for_confirmation(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    result = invoke(env, "trim", "50", input_text="n\n")

    assert result.exit_code == 1
    assert sent.calls == []


def test_trim_failure_of_the_service_is_reported(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    sent.result = CommandResult(False, "disk error")

    result = invoke(env, "trim", "50", "--yes")

    assert_clean_failure(result)
    assert "disk error" in result.output


def test_trim_offline_failure_releases_the_lock(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from chatimport import offline

    async def failing(ctx: Any, pct: int, chat: int | None) -> Any:
        raise ChatImportError("cannot trim")

    monkeypatch.setattr(offline, "offline_trim", failing)

    result = invoke(env, "trim", "25", "--yes")

    assert_clean_failure(result)
    assert env.lock_is_free()


def test_trim_end_to_end_on_a_real_folder(env: Env) -> None:
    folder = env.make_chat(CHAT_ID, "Example group", range(1, 41))

    result = invoke(env, "trim", "50", "--yes")

    assert result.exit_code == 0
    assert result.output.startswith("Deleted ")
    assert folder.is_dir()


# ------------------------------ pause / resume / recheck


@pytest.mark.parametrize("command", ["pause", "resume"])
def test_pause_and_resume_need_a_running_service(
    env: Env, sent: SentCommands, command: str
) -> None:
    result = invoke(env, command)

    assert_clean_failure(result)
    assert f"{command} needs the service" in result.output
    assert sent.calls == []


@pytest.mark.parametrize(
    ("command", "default_message"), [("pause", "Paused"), ("resume", "Resumed")]
)
def test_pause_and_resume_forward_the_chat_and_print_the_service_message(
    env: Env,
    running_service: FileLock,
    sent: SentCommands,
    command: str,
    default_message: str,
) -> None:
    quiet = invoke(env, command)
    sent.result = CommandResult(True, "custom text")
    loud = invoke(env, command, "--chat", "Example")

    assert default_message in quiet.output
    assert "custom text" in loud.output
    assert sent.calls == [(command, {"chat": None}), (command, {"chat": "Example"})]


def test_recheck_needs_a_running_service(env: Env, sent: SentCommands) -> None:
    result = invoke(env, "recheck")

    assert_clean_failure(result)
    assert "recheck needs the service" in result.output


def test_recheck_forwards_chat_and_days(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    result = invoke(env, "recheck", "--chat", "@example", "--days", "3")

    assert result.exit_code == 0
    assert sent.calls == [("recheck", {"chat": "@example", "days": 3})]
    assert "Recheck scheduled" in result.output


@pytest.mark.parametrize("days", ["0", "-1", "x"])
def test_recheck_rejects_invalid_days(
    env: Env, running_service: FileLock, sent: SentCommands, days: str
) -> None:
    result = invoke(env, "recheck", "--days", days)

    assert result.exit_code == 2
    assert sent.calls == []


# ----------------------------------------------------------------------------- backfill


def test_backfill_without_deeper_exits_2_before_touching_anything(
    env: Env, sent: SentCommands
) -> None:
    result = invoke(env, "backfill")

    assert_clean_failure(result, 2)
    assert "--deeper" in result.output
    assert sent.calls == []


def test_backfill_deeper_with_a_running_service_sends_the_command(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    result = invoke(env, "backfill", "--deeper", "--chat", "@example")

    assert result.exit_code == 0
    assert sent.calls == [("deeper", {"chat": "@example"})]
    assert "Deeper backfill started" in result.output


def test_backfill_deeper_offline_lowers_the_floor_of_every_chat(env: Env) -> None:
    from chatimport.storage.layout import find_chat_folder
    from chatimport.storage.state import load_state, save_state

    folder = env.make_chat(CHAT_ID, "Example group")
    state = load_state(folder)
    assert state is not None
    save_state(folder, replace(state, floor_id=3, floor_reason="trim"))

    result = invoke(env, "backfill", "--deeper")

    assert result.exit_code == 0
    assert "Lowered the floor of 1 chat(s)" in result.output
    found = find_chat_folder(env.ctx.root, CHAT_ID)
    assert found is not None
    after = load_state(found)
    assert after is not None
    assert after.floor_id == 0
    assert after.backfill.done is False
    assert env.lock_is_free()


def test_backfill_deeper_offline_for_an_unknown_chat_fails_cleanly(env: Env) -> None:
    env.make_chat()

    result = invoke(env, "backfill", "--deeper", "--chat", "nobody")

    assert_clean_failure(result)
    assert env.lock_is_free()


def test_backfill_deeper_offline_with_no_data_lowers_zero_chats(env: Env) -> None:
    result = invoke(env, "backfill", "--deeper")

    assert result.exit_code == 0
    assert "Lowered the floor of 0 chat(s)" in result.output


# ----------------------------------------------------------------------------- check


def test_check_of_a_healthy_root_reports_no_problems(env: Env) -> None:
    env.make_chat()

    result = invoke(env, "check")

    assert result.exit_code == 0
    assert "No problems found" in result.output
    assert env.lock_is_free()


def test_check_of_an_empty_or_missing_root_reports_no_problems(env: Env) -> None:
    result = invoke(env, "check")

    assert result.exit_code == 0
    assert "No problems found" in result.output


def test_check_prints_each_issue_and_exits_1_only_for_errors(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport import integrity
    from chatimport.integrity import CheckIssue

    seen: list[tuple[bool, Any]] = []
    issues = [
        CheckIssue(CHAT_ID, "example_1", "warning", "leftover file"),
        CheckIssue(None, "orphan", "info", "no state"),
    ]

    def fake_check(root: Path, *, repair: bool, now: Any) -> list[CheckIssue]:
        seen.append((repair, now))
        return issues

    monkeypatch.setattr(integrity, "check_root", fake_check)

    result = invoke(env, "check", "--repair")

    assert result.exit_code == 0
    assert f"[warning] {CHAT_ID} example_1: leftover file" in result.output
    assert "[info] orphan: no state" in result.output
    assert seen[0][0] is True
    assert seen[0][1].tzinfo is not None

    issues.append(CheckIssue(CHAT_ID, "example_1", "error", "gap"))
    failing = invoke(env, "check")
    assert failing.exit_code == 1
    assert "[error]" in failing.output
    assert seen[1][0] is False
    assert env.lock_is_free()


def test_check_with_a_running_service_delegates(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    result = invoke(env, "check", "--repair")

    assert result.exit_code == 0
    assert sent.calls == [("check", {"repair": True})]
    assert "Check done" in result.output


def test_check_end_to_end_flags_a_corrupt_state_file(env: Env) -> None:
    folder = env.make_chat()
    (folder / "state.json").write_text("{broken", encoding="utf-8")

    result = invoke(env, "check")

    assert "No problems found" not in result.output


# ------------------------------ export-json


def test_export_json_writes_a_valid_array_into_the_exports_folder(env: Env) -> None:
    folder = env.make_chat(CHAT_ID, "Example group", range(1, 4))

    result = invoke(env, "export-json", "--chat", "Example group")

    target = folder.parent / "_exports" / f"{folder.name}.json"
    assert result.exit_code == 0
    assert f"Wrote {target}" in result.output
    data = json.loads(target.read_text(encoding="utf-8"))
    assert [item["msg_id"] for item in data] == [1, 2, 3]


def test_export_json_honours_an_explicit_output_path(env: Env) -> None:
    env.make_chat(CHAT_ID, "Example group", range(1, 3))
    out = env.home / "out" / "chat.json"

    result = invoke(env, "export-json", "--chat", str(CHAT_ID), "--out", str(out))

    assert result.exit_code == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 2


def test_export_json_of_an_unknown_chat_fails_cleanly(env: Env) -> None:
    env.make_chat()

    result = invoke(env, "export-json", "--chat", "nobody")

    assert_clean_failure(result)
    assert "no known chat" in result.output


def test_export_json_of_a_numeric_id_without_stored_data_fails_cleanly(env: Env) -> None:
    result = invoke(env, "export-json", "--chat", "-1005550001")

    assert_clean_failure(result)
    assert "no stored data" in result.output


def test_export_json_requires_the_chat_option(env: Env) -> None:
    assert invoke(env, "export-json").exit_code == 2


# ----------------------------------------------------------------------------- set-root


@pytest.fixture
def move_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, Path, bool]]:
    from chatimport import setroot

    calls: list[tuple[Path, Path, bool]] = []

    async def fake_move(old: Path, new: Path, *, move: bool) -> None:
        calls.append((old, new, move))

    monkeypatch.setattr(setroot, "move_root", fake_move)
    return calls


def test_set_root_offline_with_move_moves_the_data_and_rewrites_the_config(
    env: Env, move_calls: list[Any]
) -> None:
    target = env.home / "elsewhere"

    result = invoke(env, "set-root", str(target), "--move")

    expected = target / "ChatImport"
    assert result.exit_code == 0
    assert f"Output folder is now {expected}" in result.output
    assert move_calls == [(env.ctx.root, expected, True)]
    config_text = env.ctx.paths.config_file.read_text(encoding="utf-8")
    assert "root_dir" in config_text
    assert "api_hash" in config_text
    assert env.lock_is_free()


def test_set_root_without_move_asks_first_and_does_not_move(
    env: Env, move_calls: list[Any]
) -> None:
    declined = invoke(env, "set-root", str(env.home / "a"), input_text="\n")
    assert declined.exit_code == 1
    assert "stays there and chats are refetched" in declined.output
    assert "root_dir" not in env.ctx.paths.config_file.read_text(encoding="utf-8")

    accepted = invoke(env, "set-root", str(env.home / "a"), input_text="y\n")
    assert accepted.exit_code == 0
    assert move_calls == []
    assert "root_dir" in env.ctx.paths.config_file.read_text(encoding="utf-8")


def test_set_root_yes_skips_the_question(env: Env, move_calls: list[Any]) -> None:
    result = invoke(env, "set-root", str(env.home / "a"), "--yes")

    assert result.exit_code == 0
    assert "Continue" not in result.output


def test_set_root_with_a_running_service_delegates_with_the_normalised_path(
    env: Env, running_service: FileLock, sent: SentCommands, move_calls: list[Any]
) -> None:
    result = invoke(env, "set-root", str(env.home / "new"), "--move")

    expected = str(env.home / "new" / "ChatImport")
    assert result.exit_code == 0
    assert sent.calls == [("set_root", {"path": expected, "move": True})]
    assert expected in result.output
    assert move_calls == []
    assert "root_dir" not in env.ctx.paths.config_file.read_text(encoding="utf-8")


def test_set_root_does_not_double_the_chatimport_suffix(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    invoke(env, "set-root", str(env.home / "Data" / "chatimport"), "--move")

    assert sent.calls[0][1] == {"path": str(env.home / "Data" / "chatimport"), "move": True}


@pytest.mark.parametrize("where", ["same", "inside"])
def test_set_root_rejects_unusable_targets_before_changing_anything(
    env: Env, move_calls: list[Any], where: str
) -> None:
    env.ctx.root.mkdir(parents=True)
    target = {
        "same": env.ctx.root,
        "inside": env.ctx.root / "sub" / "ChatImport",
    }[where]

    result = invoke(env, "set-root", str(target), "--move")

    assert_clean_failure(result)
    assert move_calls == []
    assert "root_dir" not in env.ctx.paths.config_file.read_text(encoding="utf-8")


def test_set_root_prints_warnings_to_stderr_and_continues(env: Env, move_calls: list[Any]) -> None:
    target = env.home / "OneDrive" / "stuff"

    result = invoke(env, "set-root", str(target), "--move")

    assert result.exit_code == 0
    assert "warning: the folder is inside OneDrive" in result.stderr


def test_set_root_move_failure_keeps_the_old_config_and_releases_the_lock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport import setroot

    async def failing(old: Path, new: Path, *, move: bool) -> None:
        raise ChatImportError("copy failed")

    monkeypatch.setattr(setroot, "move_root", failing)

    result = invoke(env, "set-root", str(env.home / "dest"), "--move")

    assert_clean_failure(result)
    assert "copy failed" in result.output
    assert "root_dir" not in env.ctx.paths.config_file.read_text(encoding="utf-8")
    assert env.lock_is_free()


# ------------------------------ global options


def test_root_option_overrides_the_environment(env: Env) -> None:
    other = env.home / "other"
    (other / "ChatImport").mkdir(parents=True)
    (other / "ChatImport" / "_status.json").write_text(
        json.dumps({"service": "running", "chats": [], "disk": {}, "total_bytes": 0}),
        encoding="utf-8",
    )

    result = env.runner.invoke(cli.app, ["--root", str(other), "status"])

    assert result.exit_code == 0
    assert "0 chats" in result.output


@pytest.mark.parametrize(
    "command",
    [
        "login",
        "dialogs",
        "run",
        "tray",
        "status",
        "trim",
        "pause",
        "resume",
        "recheck",
        "backfill",
        "check",
        "export-json",
        "set-root",
    ],
)
def test_every_command_documents_itself(env: Env, command: str) -> None:
    result = invoke(env, command, "--help")

    assert result.exit_code == 0
    assert "Usage" in result.output


def test_instance_lock_context_releases_when_the_body_raises(env: Env) -> None:
    with pytest.raises(RuntimeError), cli._instance_lock(env.ctx):
        raise RuntimeError

    assert env.lock_is_free()
