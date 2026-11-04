from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from chatimport.storage.layout import (
    MAX_PART_NUMBER,
    SERVICE_PREFIX,
    chat_folder_name,
    find_chat_folder,
    iter_chat_folders,
    list_parts,
    month_key,
    parse_part_name,
    part_file_name,
    part_key,
    slugify,
)
from chatimport.storage.state import save_state
from tests.unit.storage.helpers import JA, RU_UPPER, chars, fresh_state

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Example Group", "example_group"),
        ("  spaced   out  ", "spaced_out"),
        (RU_UPPER, "privet"),
        ("\U0001f600\U0001f680", "chat"),
        (JA, "chat"),
        (chars(0x43, 0x61, 0x66, 0xE9, 0x20, 0xD1, 0x61, 0x6E, 0x64, 0xFA), "cafe_nandu"),
        ("".join(chr(0xFF00 + ord(c) - 0x20) for c in "fullwidth"), "fullwidth"),
        (chr(0xFB01) + "nance", "finance"),
        ("CON", "con"),
        ("NUL.", "nul"),
        ("com1.txt", "com1_txt"),
        ("trailing dots...", "trailing_dots"),
        ("a..b", "a_b"),
        ("a__b", "a_b"),
        ("-abc-", "abc"),
        ("___", "chat"),
        ("---", "chat"),
        ("!!!???", "chat"),
        ("", "chat"),
        ("../../etc/passwd", "etc_passwd"),
        ('<>:"/\\|?*', "chat"),
        ("_status", "status"),
        ("keep-dash_and_underscore", "keep-dash_and_underscore"),
        ("a" * 39 + "_b", "a" * 39),
        ("a" * 100, "a" * 40),
        ("x" * 40 + "yyy", "x" * 40),
    ],
)
def test_slugify_table(name: str, expected: str) -> None:
    assert slugify(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "Hello World",
        RU_UPPER + " mir",
        "a" * 200,
        "__x__",
        "\x00\x01 control",
        "tab\tand\nnewline",
        "\U0001f600 smile \U0001f600",
        "COM1",
        "Aux",
        "\ud800 lone surrogate",
    ],
)
def test_slugify_is_always_a_safe_idempotent_folder_component(name: str) -> None:
    slug = slugify(name)
    assert slug
    assert len(slug) <= 40
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in slug)
    assert not slug.startswith(SERVICE_PREFIX)
    assert slug[0] not in "-."
    assert slug[-1] not in "-_."
    assert slugify(slug) == slug


def test_chat_folder_name_appends_the_signed_chat_id() -> None:
    assert chat_folder_name("Example Group", -1001234567890) == "example_group_-1001234567890"
    assert chat_folder_name("Example", 42) == "example_42"
    assert chat_folder_name("", 7) == "chat_7"


def test_chat_folder_name_of_a_reserved_device_name_is_not_reserved() -> None:
    assert chat_folder_name("CON", -1) == "con_-1"


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC), "2026-10"),
        (datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=UTC), "2026-09"),
        (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), "2026-12"),
        (datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC), "2027-01"),
        (datetime(2026, 10, 1, 2, 0, 0, tzinfo=timezone(timedelta(hours=3))), "2026-09"),
        (datetime(2026, 9, 30, 21, 0, 0, tzinfo=timezone(timedelta(hours=-3))), "2026-10"),
        (datetime(2024, 2, 29, 12, 0, 0, tzinfo=UTC), "2024-02"),
    ],
)
def test_month_key_uses_the_utc_month(moment: datetime, expected: str) -> None:
    assert month_key(moment) == expected


def test_part_name_helpers_agree() -> None:
    assert part_file_name("2026-10", 1) == "2026-10_001.jsonl"
    assert part_file_name("2026-10", 999) == "2026-10_999.jsonl"
    assert part_key("2026-10", 12) == "2026-10_012"


@pytest.mark.parametrize("part", [1, 2, 9, 10, 99, 100, MAX_PART_NUMBER])
def test_part_name_round_trips_through_parse(part: int) -> None:
    assert parse_part_name(part_file_name("2026-10", part)) == ("2026-10", part)


def test_part_names_sort_chronologically_as_text() -> None:
    names = [part_file_name(m, p) for m in ("2026-09", "2026-10") for p in (1, 2, 10, 100)]
    assert names == sorted(names)


def test_part_number_above_the_limit_does_not_round_trip() -> None:
    assert parse_part_name(part_file_name("2026-10", MAX_PART_NUMBER + 1)) is None


@pytest.mark.parametrize(
    "name",
    [
        "",
        "state.json",
        "2026-10_01.jsonl",
        "2026-10_0001.jsonl",
        "2026-10_001.json",
        "2026-10_001.jsonl.tmp",
        ".2026-10_001.jsonl.tmp",
        "2026-1_001.jsonl",
        "26-10_001.jsonl",
        "x2026-10_001.jsonl",
        "2026-10-001.jsonl",
        "2026-10_abc.jsonl",
        "_status.json",
        "2026-10_001.jsonl.bak",
        " 2026-10_001.jsonl",
    ],
)
def test_parse_part_name_rejects_malformed_names(name: str) -> None:
    assert parse_part_name(name) is None


@pytest.mark.parametrize(
    "name",
    [
        "2026-10_001.jsonl\n",
        "".join(chr(0x660 + int(c)) if c.isdigit() else c for c in "2026-10_001") + ".jsonl",
        "2026-13_001.jsonl",
        "2026-00_001.jsonl",
        "2026-10_000.jsonl",
    ],
)
def test_parse_part_name_is_strict_about_the_documented_format(name: str) -> None:
    assert parse_part_name(name) is None


def test_list_parts_is_sorted_and_ignores_everything_else(tmp_path: Path) -> None:
    folder = tmp_path / "chat"
    folder.mkdir()
    for name in ("2026-10_001.jsonl", "2026-09_002.jsonl", "2026-09_001.jsonl"):
        (folder / name).write_text("", encoding="utf-8")
    (folder / "state.json").write_text("{}", encoding="utf-8")
    (folder / "notes.jsonl").write_text("", encoding="utf-8")
    (folder / ".2026-10_001.jsonl.tmp").write_text("", encoding="utf-8")
    (folder / "2026-08_001.jsonl").mkdir()
    assert [p.name for p in list_parts(folder)] == [
        "2026-09_001.jsonl",
        "2026-09_002.jsonl",
        "2026-10_001.jsonl",
    ]


def test_list_parts_of_a_missing_folder_or_a_file_is_empty(tmp_path: Path) -> None:
    assert list_parts(tmp_path / "missing") == []
    plain = tmp_path / "plain"
    plain.write_text("x", encoding="utf-8")
    assert list_parts(plain) == []


def test_iter_chat_folders_skips_service_entries_and_files(tmp_path: Path) -> None:
    for name in ("b_2", "a_1", "_hidden_service", "_x"):
        (tmp_path / name).mkdir()
    (tmp_path / "_status.json").write_text("{}", encoding="utf-8")
    (tmp_path / "stray.txt").write_text("", encoding="utf-8")
    assert [p.name for p in iter_chat_folders(tmp_path)] == ["a_1", "b_2"]


def test_iter_chat_folders_of_a_missing_root_or_a_file_is_empty(tmp_path: Path) -> None:
    assert list(iter_chat_folders(tmp_path / "missing")) == []
    plain = tmp_path / "plain"
    plain.write_text("x", encoding="utf-8")
    assert list(iter_chat_folders(plain)) == []


def _folder_with_state(root: Path, name: str, chat_id: int) -> Path:
    folder = root / name
    save_state(folder, fresh_state(chat_id))
    return folder


def test_find_chat_folder_prefers_the_state_over_the_folder_name(tmp_path: Path) -> None:
    renamed = _folder_with_state(tmp_path, "renamed_by_hand", -1001)
    _folder_with_state(tmp_path, "other_-1002", -1002)
    assert find_chat_folder(tmp_path, -1001) == renamed


def test_find_chat_folder_does_not_trust_a_name_suffix_when_the_state_says_otherwise(
    tmp_path: Path,
) -> None:
    _folder_with_state(tmp_path, "liar_-1001", -999)
    assert find_chat_folder(tmp_path, -1001) is None


def test_find_chat_folder_falls_back_to_the_suffix_for_a_broken_state(tmp_path: Path) -> None:
    folder = tmp_path / "x_-1001"
    folder.mkdir()
    (folder / "state.json").write_text("{broken", encoding="utf-8")
    assert find_chat_folder(tmp_path, -1001) == folder


def test_find_chat_folder_state_match_beats_an_earlier_suffix_fallback(tmp_path: Path) -> None:
    broken = tmp_path / "a_-1001"
    broken.mkdir()
    real = _folder_with_state(tmp_path, "z_renamed", -1001)
    assert find_chat_folder(tmp_path, -1001) == real


def test_find_chat_folder_with_two_state_matches_returns_the_first_sorted(
    tmp_path: Path,
) -> None:
    first = _folder_with_state(tmp_path, "a_dup", -5)
    _folder_with_state(tmp_path, "b_dup", -5)
    assert find_chat_folder(tmp_path, -5) == first


def test_find_chat_folder_first_suffix_fallback_wins_between_two_broken(tmp_path: Path) -> None:
    (tmp_path / "a_-7").mkdir()
    (tmp_path / "b_-7").mkdir()
    assert find_chat_folder(tmp_path, -7) == tmp_path / "a_-7"


@pytest.mark.parametrize(
    ("chat_id", "folder_name"),
    [(15, "x_115"), (5, "x_-5"), (-5, "x_5"), (15, "x_15_extra"), (1, "x_1x")],
)
def test_find_chat_folder_suffix_requires_the_exact_id(
    tmp_path: Path, chat_id: int, folder_name: str
) -> None:
    (tmp_path / folder_name).mkdir()
    assert find_chat_folder(tmp_path, chat_id) is None


def test_find_chat_folder_ignores_service_folders_and_missing_root(tmp_path: Path) -> None:
    (tmp_path / "_x_-5").mkdir()
    assert find_chat_folder(tmp_path, -5) is None
    assert find_chat_folder(tmp_path / "missing", -5) is None


def test_find_chat_folder_ignores_files_in_the_root(tmp_path: Path) -> None:
    (tmp_path / "x_-5").write_text("not a folder", encoding="utf-8")
    assert find_chat_folder(tmp_path, -5) is None
