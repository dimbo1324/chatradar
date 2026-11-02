from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport import search_index
from chatimport.search_db import SearchError
from chatimport.search_index import open_writer
from chatimport.search_indexer import IndexBuilder
from chatimport.search_types import IndexState, IndexStatus
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.interfaces.conftest import CREDENTIALS
from tests.unit.interfaces.test_cli_commands import invoke
from tests.unit.storage.helpers import chars
from tests.unit.storage.search_helpers import OTHER_CHAT

if TYPE_CHECKING:
    from pathlib import Path

    from filelock import FileLock

    from chatimport.search_types import SearchPage, SearchQuery
    from tests.unit.interfaces.conftest import Env, SentCommands

FIRST_LINE = "Example group | 2026-09-18T01:00:00Z | https://t.me/c/1234567890/5 | text 5"


def build_index(env: Env, steps: int = 1000) -> None:
    index = open_writer(env.ctx.root)
    try:
        builder = IndexBuilder(index, env.ctx.root, lambda: NOW)
        for _ in range(steps):
            if not builder.step().more:
                break
    finally:
        index.close()


def example_chat(env: Env) -> None:
    env.make_chat(CHAT_ID, "Example group", range(1, 6))


def lines_of(output: str) -> list[str]:
    return [line for line in output.splitlines() if line]


def test_search_prints_one_line_per_match_newest_first(env: Env) -> None:
    example_chat(env)
    build_index(env)
    result = invoke(env, "search", "TEXT")
    assert result.exit_code == 0
    lines = lines_of(result.output)
    assert lines[0] == FIRST_LINE
    assert [line.rsplit(" | ", 1)[1] for line in lines[:5]] == [
        f"text {i}" for i in (5, 4, 3, 2, 1)
    ]
    assert lines[5] == "5 of 5 matches"
    assert len(lines) == 6


def test_limit_caps_the_printed_matches_but_not_the_total(env: Env) -> None:
    example_chat(env)
    build_index(env)
    result = invoke(env, "search", "text", "--limit", "2")
    assert result.exit_code == 0
    lines = lines_of(result.output)
    assert lines[0] == FIRST_LINE
    assert lines[2] == "2 of 5 matches"
    assert len(lines) == 3


@pytest.mark.parametrize("value", ["0", "1001", "-3", "many"])
def test_a_bad_limit_is_a_usage_error(env: Env, value: str) -> None:
    result = invoke(env, "search", "text", "--limit", value)
    assert result.exit_code == 2


def test_chat_narrows_the_search_by_title_or_id(env: Env) -> None:
    example_chat(env)
    env.make_chat(OTHER_CHAT, "Other chat", range(1, 3))
    build_index(env)
    assert lines_of(invoke(env, "search", "text").output)[-1] == "7 of 7 matches"
    by_title = invoke(env, "search", "text", "--chat", "Example group")
    assert lines_of(by_title.output)[-1] == "5 of 5 matches"
    by_id = invoke(env, "search", "text", "--chat", str(OTHER_CHAT))
    assert by_id.exit_code == 0
    assert lines_of(by_id.output)[-1] == "2 of 2 matches"
    assert all(line.startswith("Other chat | ") for line in lines_of(by_id.output)[:-1])


def test_an_unknown_chat_is_a_clean_failure(env: Env) -> None:
    example_chat(env)
    build_index(env)
    result = invoke(env, "search", "text", "--chat", "nobody")
    assert result.exit_code == 1
    assert "no known chat matches" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (["--since", "2026-09-18"], 2),
        (["--until", "2026-09-17"], 3),
        (["--until", "2026-09-17T22:00:00Z"], 1),
        (["--since", "2026-09-17T22:00:00+00:00", "--until", "2026-09-17T23:30:00"], 2),
        (["--since", "2026-09-17T19:00:00-03:00"], 4),
        (["--since", "2026-09-19"], 0),
    ],
)
def test_since_and_until_cut_by_utc_moment(env: Env, options: list[str], expected: int) -> None:
    example_chat(env)
    build_index(env)
    result = invoke(env, "search", "text", *options)
    assert result.exit_code == 0
    last = lines_of(result.output)[-1]
    assert last == (f"{expected} of {expected} matches" if expected else "No matches")


@pytest.mark.parametrize("option", ["--since", "--until"])
def test_a_bad_date_is_a_usage_error(env: Env, option: str) -> None:
    result = invoke(env, "search", "text", option, "yesterday")
    assert result.exit_code == 2
    assert f"{option} must be a date" in result.output


def test_line_breaks_in_a_message_stay_on_one_line(env: Env) -> None:
    folder = env.ctx.root / chat_folder_name("Notes", -5)
    writer = ChunkWriter(folder, 10**6)
    text = "first line\nsecond line\r\nthird" + chars(0x2028) + "fourth"
    writer.append(new_state(-5, "Notes", None, NOW), [msg(1, chat_id=-5, text=text)])
    build_index(env)
    result = invoke(env, "search", "second")
    assert result.exit_code == 0
    assert lines_of(result.output) == [
        "Notes | 2026-09-17T21:00:00Z | - | first line\\nsecond line\\nthird\\nfourth",
        "1 of 1 matches",
    ]


def test_no_match_says_so_and_succeeds(env: Env) -> None:
    example_chat(env)
    build_index(env)
    result = invoke(env, "search", "zzz")
    assert result.exit_code == 0
    assert lines_of(result.output) == ["No matches"]


def test_without_an_index_the_command_says_what_to_do(env: Env) -> None:
    example_chat(env)
    result = invoke(env, "search", "text")
    assert result.exit_code == 1
    assert "there is no search index yet" in result.output


def test_a_damaged_index_counts_as_missing(env: Env) -> None:
    example_chat(env)
    (env.ctx.root / "_search.db").write_bytes(b"this is not a database " * 50)
    result = invoke(env, "search", "text")
    assert result.exit_code == 1
    assert "there is no search index yet" in result.output


def test_search_turned_off_in_the_config_is_named_when_there_is_no_index(env: Env) -> None:
    example_chat(env)
    env.ctx.paths.config_file.write_text(
        CREDENTIALS + "[search]\nenabled = false\n", encoding="utf-8"
    )
    result = invoke(env, "search", "text")
    assert result.exit_code == 1
    assert "search is turned off" in result.output


def test_an_existing_index_is_searched_even_when_the_setting_is_off(env: Env) -> None:
    example_chat(env)
    build_index(env)
    env.ctx.paths.config_file.write_text(
        CREDENTIALS + "[search]\nenabled = false\n", encoding="utf-8"
    )
    result = invoke(env, "search", "text", "--limit", "1")
    assert result.exit_code == 0
    assert lines_of(result.output)[0] == FIRST_LINE


def test_an_index_still_building_is_searched_with_a_warning(env: Env) -> None:
    example_chat(env)
    env.make_chat(OTHER_CHAT, "Other chat", range(1, 3))
    build_index(env, steps=1)
    result = invoke(env, "search", "text")
    assert result.exit_code == 0
    assert "the index is still being built (5 of 7 messages)" in result.output
    assert lines_of(result.output)[-1] == "5 of 5 matches"


def test_search_works_beside_a_running_service_and_sends_nothing(
    env: Env, running_service: FileLock, sent: SentCommands
) -> None:
    example_chat(env)
    build_index(env)
    result = invoke(env, "search", "text")
    assert result.exit_code == 0
    assert lines_of(result.output)[0] == FIRST_LINE
    assert sent.calls == []


class BrokenBackend:
    def __init__(self) -> None:
        self.closed = False

    def status(self) -> IndexStatus:
        return IndexStatus(IndexState.READY, 1, 1, NOW)

    def search(self, query: SearchQuery) -> SearchPage:
        raise SearchError("the search index cannot be read right now")

    def close(self) -> None:
        self.closed = True


def test_a_failing_backend_is_a_clean_error_and_is_closed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = BrokenBackend()

    def opened(_root: Path) -> BrokenBackend:
        return backend

    monkeypatch.setattr(search_index, "open_reader", opened)
    result = invoke(env, "search", "text")
    assert result.exit_code == 1
    assert "cannot be read right now" in result.output
    assert "Traceback" not in result.output
    assert backend.closed


def test_search_documents_itself(env: Env) -> None:
    result = invoke(env, "search", "--help")
    assert result.exit_code == 0
    assert "Usage" in result.output
    assert "--since" in result.output
    assert "--until" in result.output
    assert "Search" in invoke(env, "--help").output
