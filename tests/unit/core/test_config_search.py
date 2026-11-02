from __future__ import annotations

from pathlib import Path

import pytest

from chatimport.config import Config, ConfigError, SearchConfig, load_config, parse_config

REPO = Path(__file__).resolve().parents[3]


def test_search_is_on_by_default_and_checks_every_five_seconds() -> None:
    assert Config().search == SearchConfig(True, 5)


def test_a_search_section_is_parsed() -> None:
    config = parse_config({"search": {"enabled": False, "interval_seconds": 30}})
    assert config.search == SearchConfig(False, 30)


def test_a_partial_section_keeps_the_other_default() -> None:
    assert parse_config({"search": {"enabled": False}}).search == SearchConfig(False, 5)
    assert parse_config({"search": {"interval_seconds": 1}}).search == SearchConfig(True, 1)


@pytest.mark.parametrize("value", [0, -1, -60])
def test_an_interval_below_one_second_is_rejected(value: int) -> None:
    with pytest.raises(ConfigError, match=r"\[search\] interval_seconds must be at least 1"):
        parse_config({"search": {"interval_seconds": value}})


@pytest.mark.parametrize(
    "section",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"interval_seconds": "5"},
        {"interval_seconds": 2.5},
        {"interval_seconds": True},
        {"nope": 1},
    ],
)
def test_wrong_types_and_keys_are_rejected(section: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_config({"search": section})


def test_a_search_section_must_be_a_table() -> None:
    with pytest.raises(ConfigError, match=r"\[search\] must be a table"):
        parse_config({"search": 3})


def test_the_example_file_documents_the_defaults() -> None:
    text = (REPO / "config.example.toml").read_text(encoding="utf-8")
    assert "[search]" in text
    assert load_config(REPO / "config.example.toml").search == SearchConfig()
