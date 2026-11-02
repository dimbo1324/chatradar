from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.config import ConfigError, load_config
from chatimport.config_edit import update_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def test_every_literal_kind_is_written_and_parsed(config_file: Path) -> None:
    update_config(
        config_file,
        {
            "media": {"enabled": True, "types": ["photo", "video"], "max_file_mb": 7},
            "backfill": {"use_takeout": False, "pause_between_requests_sec": 0.25},
            "output": {"root_dir": "D:/Data"},
        },
    )
    config = load_config(config_file)
    assert config.media.enabled is True
    assert config.media.types == ("photo", "video")
    assert config.media.max_file_mb == 7
    assert config.backfill.use_takeout is False
    assert config.backfill.pause_between_requests_sec == 0.25
    assert config.output.root_dir == "D:/Data"


def test_bool_false_and_empty_list_literals(config_file: Path) -> None:
    update_config(config_file, {"media": {"enabled": False, "types": []}})
    text = config_file.read_text(encoding="utf-8")
    assert "enabled = false" in text
    assert "types = []" in text


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_refused(config_file: Path, value: float) -> None:
    with pytest.raises(ConfigError, match="finite"):
        update_config(config_file, {"backfill": {"pause_between_requests_sec": value}})
    assert not config_file.exists()


@pytest.mark.parametrize("section", ["bad section", "1x", "a.b", "", "x]"])
def test_invalid_section_names_are_refused(config_file: Path, section: str) -> None:
    with pytest.raises(ConfigError, match="invalid section name"):
        update_config(config_file, {section: {"key": 1}})


@pytest.mark.parametrize("key", ["bad key", "1x", "a.b", ""])
def test_invalid_key_names_are_refused(config_file: Path, key: str) -> None:
    with pytest.raises(ConfigError, match="invalid key name"):
        update_config(config_file, {"output": {key: 1}})


def test_a_section_without_values_changes_nothing(config_file: Path) -> None:
    config_file.write_text("[output]\nmax_chunk_mb = 5\n", encoding="utf-8")
    update_config(config_file, {"output": {}, "media": {}})
    assert config_file.read_text(encoding="utf-8") == "[output]\nmax_chunk_mb = 5\n"


def test_a_missing_section_is_appended_and_existing_one_is_reused(config_file: Path) -> None:
    config_file.write_text("[output]\nmax_chunk_mb = 5\n", encoding="utf-8")
    update_config(config_file, {"media": {"enabled": True}, "output": {"max_chunk_mb": 9}})
    config = load_config(config_file)
    assert config.media.enabled is True
    assert config.output.max_chunk_mb == 9
    assert config_file.read_text(encoding="utf-8").count("[output]") == 1


def test_a_value_the_config_rejects_leaves_the_file_untouched(config_file: Path) -> None:
    config_file.write_text("[output]\nmax_chunk_mb = 5\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        update_config(config_file, {"backfill": {"batch_size": 0}})
    assert config_file.read_text(encoding="utf-8") == "[output]\nmax_chunk_mb = 5\n"


def test_unreadable_bytes_raise_config_error(config_file: Path) -> None:
    config_file.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigError, match="cannot read"):
        update_config(config_file, {"output": {"max_chunk_mb": 1}})


def test_a_directory_in_place_of_the_file_raises_config_error(tmp_path: Path) -> None:
    folder = tmp_path / "config.toml"
    folder.mkdir()
    with pytest.raises(ConfigError, match="cannot read"):
        update_config(folder, {"output": {"max_chunk_mb": 1}})


def test_broken_toml_in_the_file_is_reported(config_file: Path) -> None:
    config_file.write_text("[output\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot update"):
        update_config(config_file, {"media": {"enabled": True}})
