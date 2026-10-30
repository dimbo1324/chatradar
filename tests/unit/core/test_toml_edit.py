from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING

import pytest

from chatimport.toml_edit import TomlDocument, split_lines, toml_string, write_validated

if TYPE_CHECKING:
    from pathlib import Path

SECTION = re.compile(r"^\s*\[\s*s\s*\]\s*(#.*)?$")


def edited(text: str, key: str = "k", value: str = '"new"') -> str:
    document = TomlDocument(text)
    tables = document.find_tables(SECTION)
    if tables:
        document.set_value(tables[0], key, value)
    else:
        document.append_block(["[s]", f"{key} = {value}"])
    return document.text()


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('[s]\nk = "old"\n', '[s]\nk = "new"\n'),
        ('[s]\r\nk = "old"\r\n', '[s]\r\nk = "new"\r\n'),
        ('[s]\nk = "old"  # keep me\n', '[s]\nk = "new"  # keep me\n'),
        ('[s]\nk = "a#b"  # c\n', '[s]\nk = "new"  # c\n'),
        ("[s]\nk = 'a#b'# c\n", '[s]\nk = "new"# c\n'),
        ('[s]\nk="old"', '[s]\nk="new"'),
        ("[s]\nother = 1\n", '[s]\nother = 1\nk = "new"\n'),
        ("[s]\nother = 1\n# note\n\n[t]\n", '[s]\nother = 1\nk = "new"\n# note\n\n[t]\n'),
        ("[s]\nother = 1", '[s]\nother = 1\nk = "new"\n'),
        ("[s]\n[t]\n", '[s]\nk = "new"\n[t]\n'),
        ("", '[s]\nk = "new"\n'),
        ("[t]\nx = 1", '[t]\nx = 1\n\n[s]\nk = "new"\n'),
        ("[t]\nx = 1\n\n", '[t]\nx = 1\n\n[s]\nk = "new"\n'),
        ("[t]\r\nx = 1\r\n", '[t]\r\nx = 1\r\n\r\n[s]\r\nk = "new"\r\n'),
    ],
)
def test_set_value_table(before: str, after: str) -> None:
    assert edited(before) == after


def test_a_header_inside_a_multiline_string_is_ignored() -> None:
    text = '[t]\nx = """\n[s]\nk = "trap"\n"""\n[s]\nk = "old"\n'
    result = edited(text)
    assert tomllib.loads(result) == {"t": {"x": '[s]\nk = "trap"\n'}, "s": {"k": "new"}}


def test_a_missing_key_goes_below_a_multiline_value_not_into_it() -> None:
    text = '[s]\nx = """\nline\n# not a comment\n"""\n'
    result = edited(text)
    assert tomllib.loads(result) == {"s": {"x": "line\n# not a comment\n", "k": "new"}}


def test_unicode_line_separator_inside_a_string_is_not_a_line_break() -> None:
    text = '[s]\nk = "a\u2028b"\nz = 1\n'
    assert split_lines(text) == ["[s]\n", 'k = "a\u2028b"\n', "z = 1\n"]
    assert tomllib.loads(edited(text)) == {"s": {"k": "new", "z": 1}}


def test_a_key_with_a_longer_name_is_not_taken_for_the_key() -> None:
    assert edited("[s]\nkk = 1\n") == '[s]\nkk = 1\nk = "new"\n'


@pytest.mark.parametrize("value", ['a"b', "back\\slash", "del\x7f", "\u0427\u0430\u0442", "\x00"])
def test_toml_string_round_trips(value: str) -> None:
    assert tomllib.loads(f"k = {toml_string(value)}") == {"k": value}


def test_write_validated_refuses_before_touching_the_file(tmp_path: Path) -> None:
    target = tmp_path / "x.toml"
    target.write_text("old", encoding="utf-8")

    def refuse(_text: str) -> None:
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        write_validated(target, "new", refuse)
    assert target.read_text(encoding="utf-8") == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.toml"]


def test_write_validated_creates_the_folder(tmp_path: Path) -> None:
    target = tmp_path / "a" / "x.toml"
    write_validated(target, "k = 1\n", tomllib.loads)
    assert target.read_bytes() == b"k = 1\n"
