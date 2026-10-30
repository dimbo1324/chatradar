"""Branches of recently fixed code that the area suites do not reach on their own."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.config import ConfigError, parse_config
from chatimport.library import add_entry, load_library, set_enabled
from chatimport.media import _identity  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path

BACKSLASH = chr(92)


def test_negative_pause_between_chats_is_rejected() -> None:
    with pytest.raises(ConfigError, match="pause_between_chats_sec"):
        parse_config({"backfill": {"pause_between_chats_sec": -1}})


def test_identity_of_a_missing_file_has_size_minus_one(tmp_path: Path) -> None:
    assert _identity(tmp_path / "missing.jsonl") == (-1, 0)


def test_set_enabled_survives_escapes_and_quotes_inside_other_strings(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    lines = [
        "[[chat]]",
        'ref = "@first"',
        'name = "a ' + BACKSLASH + '" b' + BACKSLASH + 'n"',
        "note_like = 'single # not a comment'",
        "",
        "[[chat]]",
        'ref = "@second"',
    ]
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    text = path.read_text(encoding="utf-8").replace("note_like = 'single # not a comment'", "")
    path.write_text(text, encoding="utf-8")

    set_enabled(path, "@second", False)

    entries = load_library(path).entries
    assert [(e.ref, e.enabled) for e in entries] == [("@first", True), ("@second", False)]


def test_set_enabled_handles_single_quoted_literal_strings(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    body = chr(10).join(["[[chat]]", "ref = '@lit'", "name = 'plain # not a comment'"])
    path.write_text(body + chr(10), encoding="utf-8")

    set_enabled(path, "@lit", False)

    entry = load_library(path).entries[0]
    assert (entry.name, entry.enabled) == ("plain # not a comment", False)


def test_set_enabled_ignores_keys_that_live_inside_a_multiline_string(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    body = chr(10).join(
        [
            "[[chat]]",
            'ref = "@only"',
            'name = """',
            "enabled = false",
            "text with " + BACKSLASH + 'u0041 escape and ""',
            '"""',
        ]
    )
    path.write_text(body + chr(10), encoding="utf-8")

    set_enabled(path, "@only", False)

    entry = load_library(path).entries[0]
    assert entry.enabled is False
    assert "enabled = false" in (entry.name or "")


def test_multiline_literal_string_with_a_header_lookalike_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    add_entry(path, "@a", "x")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('name = "x"', "name = '''" + chr(10) + "[[chat]]" + chr(10) + "'''"),
        encoding="utf-8",
    )
    add_entry(path, "@b")

    set_enabled(path, "@b", False)

    assert [(e.ref, e.enabled) for e in load_library(path).entries] == [
        ("@a", True),
        ("@b", False),
    ]
