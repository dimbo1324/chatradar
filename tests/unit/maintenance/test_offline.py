from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from chatimport.app import ServiceContext
from chatimport.config import Config
from chatimport.offline import (
    lower_floor,
    lower_floor_state,
    offline_trim,
    resolve_chat_selector,
)
from chatimport.paths import AppPaths
from chatimport.ports import ChatImportError
from chatimport.storage.layout import STATE_FILE, chat_folder_name
from chatimport.storage.state import BackfillState, save_state
from tests.fakes import NOW
from tests.unit.maintenance.helpers import (
    at,
    build_chat,
    message_ids,
    mmsg,
    read_state,
)

if TYPE_CHECKING:
    from pathlib import Path


def context(tmp_path: Path, library: str | None = None) -> ServiceContext:
    base = tmp_path / "app"
    base.mkdir(exist_ok=True)
    library_file = base / "chats.toml"
    if library is not None:
        library_file.write_text(library, encoding="utf-8")
    return ServiceContext(
        config=Config(), paths=AppPaths(base), root=tmp_path / "root", library_file=library_file
    )


def named_chat(
    ctx: ServiceContext,
    chat_id: int,
    title: str,
    username: str | None = None,
    folder_title: str | None = None,
) -> Path:
    chat = build_chat(ctx.root, chat_id, [[mmsg(1, chat_id=chat_id)]], title=folder_title or title)
    state = read_state(chat)
    save_state(chat.folder, replace(state, title=title, username=username))
    return chat.folder


# ---------------------------------------------------------------- offline trim


async def test_offline_trim_works_on_the_data_folder_without_a_service(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    a = build_chat(ctx.root, -1, [[mmsg(i, chat_id=-1) for i in range(1, 9)]], title="A")
    b = build_chat(ctx.root, -2, [[mmsg(i, chat_id=-2) for i in range(1, 5)]], title="B")

    report = await offline_trim(ctx, 50, None)

    assert report.per_chat == {-1: 4, -2: 2}
    assert message_ids(a) == [5, 6, 7, 8]
    assert message_ids(b) == [3, 4]
    assert (ctx.root / "_trim_log.jsonl").exists()


async def test_offline_trim_of_one_chat_leaves_the_rest(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    a = build_chat(ctx.root, -1, [[mmsg(i, chat_id=-1) for i in range(1, 5)]], title="A")
    b = build_chat(ctx.root, -2, [[mmsg(i, chat_id=-2) for i in range(1, 5)]], title="B")

    report = await offline_trim(ctx, 50, -2)

    assert report.per_chat == {-2: 2}
    assert message_ids(a) == [1, 2, 3, 4]
    assert message_ids(b) == [3, 4]


async def test_offline_trim_rejects_a_bad_percentage(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    with pytest.raises(ValueError, match="pct"):
        await offline_trim(ctx, 33, None)


# ---------------------------------------------------------------- lower floor


@pytest.mark.parametrize(
    ("floor", "oldest_done", "expected_oldest"),
    [
        (500, 0, 500),
        (500, 200, 500),
        (500, 800, 800),
        (0, 0, 0),
        (0, 40, 40),
    ],
)
def test_lower_floor_reopens_the_tail_below_the_old_floor(
    tmp_path: Path, floor: int, oldest_done: int, expected_oldest: int
) -> None:
    chat = build_chat(tmp_path / "root", -1, [[mmsg(600, chat_id=-1)]])
    save_state(
        chat.folder,
        replace(
            read_state(chat),
            floor_id=floor,
            floor_reason="manual_trim_50",
            backfill=BackfillState(done=True, head_id=900, oldest_done_id=oldest_done),
            last_id=900,
        ),
    )

    assert lower_floor_state(chat.folder, at(2026, 10, 29, 1, 2, 3)) is True

    state = read_state(chat)
    assert state.floor_id == 0
    assert state.floor_reason is None
    assert state.backfill.done is False
    assert state.backfill.oldest_done_id == expected_oldest
    assert state.backfill.head_id == 900
    assert state.last_id == 900
    assert state.updated_at == at(2026, 10, 29, 1, 2, 3)
    assert state.chunks


def test_lower_floor_state_without_a_state_file_is_false_and_creates_nothing(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "root" / "x_-1"
    folder.mkdir(parents=True)

    assert lower_floor_state(folder, NOW) is False
    assert list(folder.iterdir()) == []


def test_lower_floor_selects_chats_and_skips_unreadable_ones(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = build_chat(root, -1, [[mmsg(1, chat_id=-1)]], title="A")
    b = build_chat(root, -2, [[mmsg(1, chat_id=-2)]], title="B")
    broken = build_chat(root, -3, [[mmsg(1, chat_id=-3)]], title="C")
    for chat in (a, b):
        save_state(chat.folder, replace(read_state(chat), floor_id=7))
    (broken.folder / STATE_FILE).write_text("junk", encoding="utf-8")

    assert lower_floor(root, -2) == [-2]
    assert read_state(a).floor_id == 7
    assert read_state(b).floor_id == 0
    assert lower_floor(root, 12345) == []
    assert sorted(lower_floor(root, None)) == [-2, -1]
    assert read_state(a).floor_id == 0


def test_lower_floor_on_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert lower_floor(tmp_path / "nowhere", None) == []


# ---------------------------------------------------------------- selectors


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_empty_selector_is_an_error(tmp_path: Path, text: str) -> None:
    with pytest.raises(ChatImportError, match="empty"):
        resolve_chat_selector(context(tmp_path), text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("-1001234", -1001234), ("  42 ", 42), ("0", 0), ("-0", 0)],
)
def test_numeric_selectors_are_taken_as_chat_ids_even_when_unknown(
    tmp_path: Path, text: str, expected: int
) -> None:
    assert resolve_chat_selector(context(tmp_path), text) == expected


def test_selector_by_folder_name_and_title_ignores_case(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -10, "Chess Club")

    folder = chat_folder_name("Chess Club", -10)
    assert resolve_chat_selector(ctx, folder) == -10
    assert resolve_chat_selector(ctx, folder.upper()) == -10
    assert resolve_chat_selector(ctx, "chess club") == -10
    assert resolve_chat_selector(ctx, "  CHESS CLUB ") == -10


@pytest.mark.parametrize("text", ["@Chess_Club", "@chess_club", "Chess_Club", "chess_club"])
def test_selector_by_username_with_or_without_at_sign(tmp_path: Path, text: str) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -10, "Some Title", username="chess_club")

    assert resolve_chat_selector(ctx, text) == -10


def test_unknown_selector_names_it_in_the_error(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -10, "Chess Club")

    with pytest.raises(ChatImportError, match=r"no known chat matches 'Poker'"):
        resolve_chat_selector(ctx, "Poker")


def test_two_chats_with_the_same_title_are_ambiguous(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -10, "Twin")
    named_chat(ctx, -20, "Twin")

    with pytest.raises(ChatImportError, match="several chats"):
        resolve_chat_selector(ctx, "twin")
    assert resolve_chat_selector(ctx, "-20") == -20


def test_title_of_one_chat_equal_to_the_username_of_another_is_ambiguous(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -10, "alpha")
    named_chat(ctx, -20, "Other", username="alpha")

    with pytest.raises(ChatImportError, match="several chats"):
        resolve_chat_selector(ctx, "alpha")


def test_library_name_maps_to_the_chat_through_the_folder_name(tmp_path: Path) -> None:
    library = '[[chat]]\nref = "https://example.invalid/x"\nname = "Team Chat"\n'
    ctx = context(tmp_path, library)
    named_chat(ctx, -77, "Whatever Telegram Says", folder_title="Team Chat")

    assert resolve_chat_selector(ctx, "Team Chat") == -77
    assert resolve_chat_selector(ctx, "team chat") == -77


def test_library_ref_with_a_public_link_maps_by_username(tmp_path: Path) -> None:
    library = '[[chat]]\nref = "https://t.me/Team_Chat/"\nname = "Alias"\n'
    ctx = context(tmp_path, library)
    named_chat(ctx, -77, "Team", username="team_chat")

    assert resolve_chat_selector(ctx, "https://t.me/Team_Chat/") == -77
    assert resolve_chat_selector(ctx, "Alias") == -77


def test_library_at_username_ref_maps_to_the_chat(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "@MyGroup"\n')
    named_chat(ctx, -5, "T", username="mygroup")

    assert resolve_chat_selector(ctx, "@MyGroup") == -5


def test_library_ref_with_a_numeric_id_maps_even_without_a_folder(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "-100555"\nname = "Fresh"\n')

    assert resolve_chat_selector(ctx, "Fresh") == -100555


def test_library_numeric_ref_with_a_known_folder_matches_that_chat(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "-5"\nname = "Fives"\n')
    named_chat(ctx, -5, "Totally Different")

    assert resolve_chat_selector(ctx, "Fives") == -5


def test_library_name_that_is_also_another_chats_title_is_ambiguous(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "-5"\nname = "Fives"\n')
    named_chat(ctx, -5, "Totally Different")
    named_chat(ctx, -6, "Fives")

    with pytest.raises(ChatImportError, match="several chats"):
        resolve_chat_selector(ctx, "Fives")


def test_library_title_ref_matches_the_chat_title(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "Book Club"\n')
    named_chat(ctx, -9, "BOOK club")

    assert resolve_chat_selector(ctx, "Book Club") == -9


def test_a_joinchat_library_ref_is_not_mistaken_for_a_username(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "https://t.me/joinchat/AbCdEf"\nname = "Private"\n')
    named_chat(ctx, -9, "Private Stuff", username="joinchat")

    with pytest.raises(ChatImportError, match="no known chat matches"):
        resolve_chat_selector(ctx, "Private")


def test_a_broken_library_does_not_hide_the_known_chats(tmp_path: Path) -> None:
    ctx = context(tmp_path, "this is [not toml")
    named_chat(ctx, -10, "Chess Club")

    assert resolve_chat_selector(ctx, "Chess Club") == -10
    with pytest.raises(ChatImportError, match="no known chat"):
        resolve_chat_selector(ctx, "Absent")


def test_a_missing_library_file_is_fine(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -10, "Chess Club")

    assert resolve_chat_selector(ctx, "chess club") == -10


def test_selector_ignores_chats_whose_state_is_unreadable(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    folder = named_chat(ctx, -10, "Chess Club")
    (folder / STATE_FILE).write_text("junk", encoding="utf-8")

    with pytest.raises(ChatImportError):
        resolve_chat_selector(ctx, "Chess Club")


# ---------------------------------------------------------------- i18n and refs

WORK = "\u0420\u0430\u0431\u043e\u0442\u0430"
HOME = "\u0414\u043e\u043c"
NEWS = "\u041d\u043e\u0432\u043e\u0441\u0442\u0438"
FIRE = "\U0001f525\U0001f525"


def invite_library(name: str) -> str:
    return f'[[chat]]\nref = "https://t.me/+x"\nname = "{name}"\n'


def test_selector_by_cyrillic_name_does_not_match_other_cyrillic_chats(tmp_path: Path) -> None:
    ctx = context(tmp_path, invite_library(NEWS))
    named_chat(ctx, -1001, WORK)
    named_chat(ctx, -1002, HOME)

    with pytest.raises(ChatImportError, match="no known chat matches"):
        resolve_chat_selector(ctx, NEWS)


def test_selector_by_name_with_only_other_chat_on_disk(tmp_path: Path) -> None:
    ctx = context(tmp_path, invite_library(NEWS))
    named_chat(ctx, -1001, WORK)

    with pytest.raises(ChatImportError, match="no known chat matches"):
        resolve_chat_selector(ctx, NEWS)


def test_a_name_without_letters_never_matches_through_the_fallback_folder(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path, invite_library(FIRE))
    named_chat(ctx, -1001, "\U0001f600")

    with pytest.raises(ChatImportError, match="no known chat matches"):
        resolve_chat_selector(ctx, FIRE)


def test_a_cyrillic_library_name_maps_to_its_own_folder(tmp_path: Path) -> None:
    ctx = context(tmp_path, invite_library(NEWS))
    named_chat(ctx, -1001, WORK)
    named_chat(ctx, -1003, "Telegram title", folder_title=NEWS)

    assert resolve_chat_selector(ctx, NEWS) == -1003
    assert resolve_chat_selector(ctx, NEWS.lower()) == -1003


def test_selector_matches_telegram_me_entry(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "https://telegram.me/Team_Chat?x=1"\n')
    named_chat(ctx, -77, "Team", username="team_chat")

    assert resolve_chat_selector(ctx, "https://telegram.me/Team_Chat?x=1") == -77


def test_selector_by_title_ignores_the_unicode_form(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    named_chat(ctx, -9, "Caf\u00e9 Espa\u00f1a")

    assert resolve_chat_selector(ctx, "CAFE\u0301 ESPAN\u0303A") == -9


def test_library_channel_link_ref_maps_by_its_id(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[[chat]]\nref = "https://t.me/c/555/9"\nname = "Linked"\n')
    named_chat(ctx, -1000000000555, "Whatever")

    assert resolve_chat_selector(ctx, "Linked") == -1000000000555


def unreadable_for(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    from chatimport import offline
    from chatimport.storage.state import StateUnreadable, load_state

    def flaky(path: Path) -> object:
        if path == folder:
            raise StateUnreadable(path, PermissionError("locked"))
        return load_state(path)

    monkeypatch.setattr(offline, "load_state", flaky)


def test_selector_refuses_while_a_state_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path)
    locked = named_chat(ctx, -10, "Twin")
    named_chat(ctx, -20, "Twin")
    unreadable_for(monkeypatch, locked)

    with pytest.raises(ChatImportError, match="cannot be read right now"):
        resolve_chat_selector(ctx, "Twin")
    assert resolve_chat_selector(ctx, "-20") == -20


def test_lower_floor_skips_an_unreadable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    locked = build_chat(root, -1, [[mmsg(1, chat_id=-1)]], title="Locked").folder
    build_chat(root, -2, [[mmsg(1, chat_id=-2)]], title="Fine")
    unreadable_for(monkeypatch, locked)

    assert lower_floor(root, None) == [-2]


async def test_offline_trim_of_an_unknown_chat_is_an_error(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    build_chat(ctx.root, -1, [[mmsg(1, chat_id=-1)]], title="A")

    with pytest.raises(ChatImportError, match="no chat -9"):
        await offline_trim(ctx, 50, -9)
