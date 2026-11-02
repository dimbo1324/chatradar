from __future__ import annotations

import pytest

from chatimport.config import Config, ConfigError, MergedConfig, parse_config


def test_defaults_keep_the_combined_file_off() -> None:
    assert Config().merged == MergedConfig(False, "json", 10, False)


def test_a_merged_section_is_parsed() -> None:
    config = parse_config(
        {"merged": {"enabled": True, "format": "jsonl", "every_minutes": 3, "include_names": True}}
    )
    assert config.merged == MergedConfig(True, "jsonl", 3, True)


@pytest.mark.parametrize("value", ["csv", "", "JSON"])
def test_an_unknown_format_is_rejected(value: str) -> None:
    with pytest.raises(ConfigError, match="format must be"):
        parse_config({"merged": {"format": value}})


@pytest.mark.parametrize(
    "section",
    [{"enabled": "yes"}, {"format": 1}, {"include_names": 1}, {"nope": 1}],
)
def test_wrong_types_and_keys_are_rejected(section: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_config({"merged": section})
