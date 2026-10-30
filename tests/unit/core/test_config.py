from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from chatimport.config import Config, ConfigError, load_config, parse_config

REPO = Path(__file__).resolve().parents[3]


def test_empty_mapping_gives_defaults() -> None:
    assert parse_config({}) == Config()


def test_example_template_equals_defaults() -> None:
    assert load_config(REPO / "config.example.toml") == Config()


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "absent.toml") == Config()


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"")
    assert load_config(path) == Config()


def test_comments_only_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"# nothing here\r\n\r\n")
    assert load_config(path) == Config()


def test_crlf_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"[live]\r\nflush_every_messages = 9\r\n")
    assert load_config(path).live.flush_every_messages == 9


def test_file_with_utf8_bom_loads(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xef\xbb\xbf[live]\nflush_every_messages = 9\n")
    assert load_config(path).live.flush_every_messages == 9


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[live\nx = ", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(path)


def test_duplicate_toml_key_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[live]\nflush_every_seconds = 1\nflush_every_seconds = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_non_utf8_file_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'[telegram]\napi_hash = "\xff\xfe"\n')
    with pytest.raises(ConfigError):
        load_config(path)


def test_directory_in_place_of_file_is_not_silently_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.mkdir()
    with pytest.raises(ConfigError):
        load_config(path)


def test_unknown_section_is_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown sections: bogus"):
        parse_config({"bogus": {}})


def test_unknown_sections_are_all_listed_sorted() -> None:
    with pytest.raises(ConfigError, match="unknown sections: a, b"):
        parse_config({"b": {}, "a": {}})


def test_unknown_key_names_section_and_key() -> None:
    with pytest.raises(ConfigError, match=r"\[live\] unknown keys: nope"):
        parse_config({"live": {"nope": 1}})


def test_section_names_are_case_sensitive() -> None:
    with pytest.raises(ConfigError):
        parse_config({"Live": {}})


@pytest.mark.parametrize("value", [1, "x", [], [{}], True, 1.5])
def test_section_must_be_a_table(value: object) -> None:
    with pytest.raises(ConfigError, match=r"\[telegram\] must be a table"):
        parse_config({"telegram": value})


INT_FIELDS = [
    ("telegram", "api_id"),
    ("telegram", "flood_sleep_threshold"),
    ("output", "max_chunk_mb"),
    ("library", "reload_check_seconds"),
    ("recheck", "days"),
    ("recheck", "pause_between_chats_sec"),
    ("live", "flush_every_messages"),
    ("live", "flush_every_seconds"),
    ("live", "reconcile_every_minutes"),
    ("backfill", "batch_size"),
    ("backfill", "pause_between_chats_sec"),
    ("backfill", "max_parallel_chats"),
    ("disk", "low_watermark_gb"),
    ("disk", "high_watermark_gb"),
    ("disk", "check_every_minutes"),
    ("disk", "protect_recent_days"),
    ("watch", "check_every_seconds"),
    ("watch", "confirm_checks"),
    ("media", "max_file_mb"),
]


@pytest.mark.parametrize(("section", "key"), INT_FIELDS)
@pytest.mark.parametrize("bad", [True, False, 1.5, "5", [5], {"a": 1}, None])
def test_int_fields_reject_other_types(section: str, key: str, bad: object) -> None:
    with pytest.raises(ConfigError, match=rf"\[{section}\] {key} must be int"):
        parse_config({section: {key: bad}})


BOOL_FIELDS = [
    ("output", "include_sender_names"),
    ("output", "include_raw"),
    ("recheck", "enabled"),
    ("backfill", "use_takeout"),
    ("media", "enabled"),
    ("events", "track_edits"),
    ("events", "track_deletes"),
]


@pytest.mark.parametrize(("section", "key"), BOOL_FIELDS)
@pytest.mark.parametrize("bad", [0, 1, "true", "false", None, [True]])
def test_bool_fields_reject_other_types(section: str, key: str, bad: object) -> None:
    with pytest.raises(ConfigError, match=rf"\[{section}\] {key} must be bool"):
        parse_config({section: {key: bad}})


@pytest.mark.parametrize(("section", "key"), BOOL_FIELDS)
def test_bool_fields_accept_both_values(section: str, key: str) -> None:
    for value in (True, False):
        config = parse_config({section: {key: value}})
        assert getattr(getattr(config, section), key) is value


STR_FIELDS = [
    ("telegram", "api_hash"),
    ("output", "root_dir"),
    ("library", "file"),
    ("recheck", "daily_at"),
]


@pytest.mark.parametrize(("section", "key"), STR_FIELDS)
@pytest.mark.parametrize("bad", [1, True, 1.5, ["a"], {"a": "b"}, None])
def test_string_fields_reject_other_types(section: str, key: str, bad: object) -> None:
    with pytest.raises(ConfigError, match=rf"\[{section}\] {key} must be str"):
        parse_config({section: {key: bad}})


def test_float_field_accepts_int_and_coerces_to_float() -> None:
    config = parse_config({"backfill": {"pause_between_requests_sec": 2}})
    assert config.backfill.pause_between_requests_sec == 2.0
    assert isinstance(config.backfill.pause_between_requests_sec, float)


def test_float_field_keeps_fraction() -> None:
    config = parse_config({"backfill": {"pause_between_requests_sec": 0.25}})
    assert config.backfill.pause_between_requests_sec == 0.25


@pytest.mark.parametrize("bad", [True, False, "1.0", [1.0], None])
def test_float_field_rejects_other_types(bad: object) -> None:
    with pytest.raises(ConfigError, match="pause_between_requests_sec must be float"):
        parse_config({"backfill": {"pause_between_requests_sec": bad}})


def test_media_types_become_a_tuple() -> None:
    config = parse_config({"media": {"types": ["photo", "voice"]}})
    assert config.media.types == ("photo", "voice")


def test_media_types_empty_list_is_empty_tuple() -> None:
    assert parse_config({"media": {"types": []}}).media.types == ()


@pytest.mark.parametrize("bad", ["photo", [1], ["photo", 2], [["photo"]], [None], 5, True, None])
def test_media_types_must_be_a_list_of_strings(bad: object) -> None:
    with pytest.raises(ConfigError, match="types must be a list of strings"):
        parse_config({"media": {"types": bad}})


def test_parse_does_not_mutate_input() -> None:
    data: dict[str, Any] = {"live": {"flush_every_messages": 3}, "recheck": {}}
    parse_config(data)
    assert data == {"live": {"flush_every_messages": 3}, "recheck": {}}


def test_config_is_frozen() -> None:
    config = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.live.flush_every_seconds = 1  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]


def test_huge_integers_are_accepted() -> None:
    assert parse_config({"telegram": {"api_id": 2**70}}).telegram.api_id == 2**70


@pytest.mark.parametrize(
    ("api_id", "api_hash", "expected"),
    [(0, "", False), (1, "", False), (0, "abc", False), (-5, "abc", False), (1, "abc", True)],
)
def test_is_configured_needs_positive_id_and_hash(
    api_id: int, api_hash: str, expected: bool
) -> None:
    config = parse_config({"telegram": {"api_id": api_id, "api_hash": api_hash}})
    assert config.telegram.is_configured is expected


@pytest.mark.parametrize(
    "data",
    [
        {"output": {"max_chunk_mb": 0}},
        {"output": {"max_chunk_mb": -1}},
        {"live": {"flush_every_messages": 0}},
        {"live": {"flush_every_seconds": 0}},
        {"live": {"flush_every_messages": -3}},
        {"disk": {"low_watermark_gb": 15, "high_watermark_gb": 15}},
        {"disk": {"low_watermark_gb": 17, "high_watermark_gb": 15}},
        {"disk": {"high_watermark_gb": 10}},
        {"disk": {"low_watermark_gb": 20}},
        {"watch": {"confirm_checks": 0}},
        {"backfill": {"batch_size": 0}},
        {"backfill": {"max_parallel_chats": 0}},
        {"recheck": {"days": 0}},
        {"recheck": {"days": -7}},
    ],
)
def test_out_of_range_values_are_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        parse_config(data)


@pytest.mark.parametrize(
    "data",
    [
        {"output": {"max_chunk_mb": 1}},
        {"live": {"flush_every_messages": 1, "flush_every_seconds": 1}},
        {"disk": {"low_watermark_gb": 15, "high_watermark_gb": 16}},
        {"disk": {"low_watermark_gb": 0, "high_watermark_gb": 1}},
        {"watch": {"confirm_checks": 1}},
        {"backfill": {"batch_size": 1, "max_parallel_chats": 1}},
        {"recheck": {"days": 1}},
    ],
)
def test_boundary_values_are_accepted(data: dict[str, Any]) -> None:
    parse_config(data)


def test_watermark_ordering_is_checked_against_defaults_when_one_side_is_set() -> None:
    parse_config({"disk": {"low_watermark_gb": 16}})
    with pytest.raises(ConfigError, match="high_watermark_gb must exceed"):
        parse_config({"disk": {"low_watermark_gb": 17}})


@pytest.mark.parametrize("daily_at", ["04:00", "4:00", "00:00", "0:00", "23:59", "9:05"])
def test_daily_at_accepts_clock_times(daily_at: str) -> None:
    assert parse_config({"recheck": {"daily_at": daily_at}}).recheck.daily_at == daily_at


@pytest.mark.parametrize(
    "daily_at",
    [
        "24:00",
        "12:60",
        "ab:cd",
        "",
        "12",
        "12:",
        ":30",
        ":",
        "1:2:3",
        "-1:00",
        "12:-5",
        "+1:00",
        " 4:00",
        "4:00 ",
        "4.00",
        "4:0x",
        "25:99",
        "\u00b2:00",
        "12:\u00b30",
        "\u0664:\u0660\u0660",
        "\uff14:\uff10\uff10",
    ],
)
def test_daily_at_rejects_everything_but_ascii_hh_mm(daily_at: str) -> None:
    with pytest.raises(ConfigError, match="daily_at"):
        parse_config({"recheck": {"daily_at": daily_at}})


@pytest.mark.parametrize(
    "data",
    [
        {"library": {"reload_check_seconds": 0}},
        {"watch": {"check_every_seconds": 0}},
        {"disk": {"check_every_minutes": 0}},
        {"live": {"reconcile_every_minutes": 0}},
        {"backfill": {"pause_between_requests_sec": -1}},
    ],
)
def test_zero_or_negative_loop_intervals_are_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        parse_config(data)
