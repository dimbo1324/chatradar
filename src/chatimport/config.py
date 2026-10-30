"""Typed configuration loaded from `config.toml`; an empty or missing file gives all defaults."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, get_type_hints

if TYPE_CHECKING:
    from pathlib import Path


_DAILY_AT = re.compile(r"(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{2})")


class ConfigError(ValueError):
    """The configuration file is unreadable or holds an invalid value."""


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    api_id: int = 0
    api_hash: str = ""
    flood_sleep_threshold: int = 120

    @property
    def is_configured(self) -> bool:
        return self.api_id > 0 and bool(self.api_hash)


@dataclass(frozen=True, slots=True)
class OutputConfig:
    root_dir: str = ""
    include_sender_names: bool = True
    include_raw: bool = False
    max_chunk_mb: int = 20


@dataclass(frozen=True, slots=True)
class LibraryConfig:
    file: str = ""
    reload_check_seconds: int = 10


@dataclass(frozen=True, slots=True)
class RecheckConfig:
    enabled: bool = True
    days: int = 7
    daily_at: str = "04:00"
    pause_between_chats_sec: int = 10


@dataclass(frozen=True, slots=True)
class LiveConfig:
    flush_every_messages: int = 5
    flush_every_seconds: int = 30
    reconcile_every_minutes: int = 10


@dataclass(frozen=True, slots=True)
class BackfillConfig:
    batch_size: int = 100
    pause_between_requests_sec: float = 1.0
    pause_between_chats_sec: int = 5
    max_parallel_chats: int = 1
    use_takeout: bool = False


@dataclass(frozen=True, slots=True)
class DiskConfig:
    low_watermark_gb: int = 15
    high_watermark_gb: int = 17
    check_every_minutes: int = 5
    protect_recent_days: int = 30


@dataclass(frozen=True, slots=True)
class WatchConfig:
    check_every_seconds: int = 10
    confirm_checks: int = 2


@dataclass(frozen=True, slots=True)
class MediaConfig:
    enabled: bool = False
    types: tuple[str, ...] = ()
    max_file_mb: int = 50


@dataclass(frozen=True, slots=True)
class EventsConfig:
    track_edits: bool = True
    track_deletes: bool = True


@dataclass(frozen=True, slots=True)
class Config:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    library: LibraryConfig = field(default_factory=LibraryConfig)
    recheck: RecheckConfig = field(default_factory=RecheckConfig)
    live: LiveConfig = field(default_factory=LiveConfig)
    backfill: BackfillConfig = field(default_factory=BackfillConfig)
    disk: DiskConfig = field(default_factory=DiskConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    events: EventsConfig = field(default_factory=EventsConfig)


def _build[T](cls: type[T], raw: dict[str, Any], section: str) -> T:
    hints = get_type_hints(cls)
    unknown = sorted(set(raw) - set(hints))
    if unknown:
        raise ConfigError(f"[{section}] unknown keys: {', '.join(unknown)}")
    values: dict[str, Any] = {}
    for name, value in raw.items():
        expected = hints[name]
        if expected == tuple[str, ...]:
            items: list[Any] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in items):
                raise ConfigError(f"[{section}] {name} must be a list of strings")
            value = tuple(items)
        elif expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        elif not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ConfigError(f"[{section}] {name} must be {expected.__name__}")
        values[name] = value
    return cls(**values)


_SECTIONS: dict[str, type[Any]] = {
    "telegram": TelegramConfig,
    "output": OutputConfig,
    "library": LibraryConfig,
    "recheck": RecheckConfig,
    "live": LiveConfig,
    "backfill": BackfillConfig,
    "disk": DiskConfig,
    "watch": WatchConfig,
    "media": MediaConfig,
    "events": EventsConfig,
}


def parse_config(data: dict[str, Any]) -> Config:
    unknown = sorted(set(data) - set(_SECTIONS))
    if unknown:
        raise ConfigError(f"unknown sections: {', '.join(unknown)}")
    sections: dict[str, Any] = {}
    for name, cls in _SECTIONS.items():
        raw = data.get(name, {})
        if not isinstance(raw, dict):
            raise ConfigError(f"[{name}] must be a table")
        sections[name] = _build(cls, raw, name)  # pyright: ignore[reportUnknownArgumentType]
    config = Config(**sections)
    _validate(config)
    return config


def _validate(config: Config) -> None:
    if config.output.max_chunk_mb < 1:
        raise ConfigError("[output] max_chunk_mb must be at least 1")
    if config.live.flush_every_messages < 1 or config.live.flush_every_seconds < 1:
        raise ConfigError("[live] flush thresholds must be at least 1")
    if config.disk.high_watermark_gb <= config.disk.low_watermark_gb:
        raise ConfigError("[disk] high_watermark_gb must exceed low_watermark_gb")
    if config.watch.confirm_checks < 1:
        raise ConfigError("[watch] confirm_checks must be at least 1")
    if config.backfill.batch_size < 1 or config.backfill.max_parallel_chats < 1:
        raise ConfigError("[backfill] batch_size and max_parallel_chats must be at least 1")
    if config.recheck.days < 1:
        raise ConfigError("[recheck] days must be at least 1")
    match = _DAILY_AT.fullmatch(config.recheck.daily_at)
    if match is None or int(match["hour"]) > 23 or int(match["minute"]) > 59:
        raise ConfigError("[recheck] daily_at must look like HH:MM")
    intervals = {
        "[library] reload_check_seconds": config.library.reload_check_seconds,
        "[watch] check_every_seconds": config.watch.check_every_seconds,
        "[disk] check_every_minutes": config.disk.check_every_minutes,
        "[live] reconcile_every_minutes": config.live.reconcile_every_minutes,
    }
    for name, value in intervals.items():
        if value < 1:
            raise ConfigError(f"{name} must be at least 1")
    if config.backfill.pause_between_requests_sec < 0 or config.recheck.pause_between_chats_sec < 0:
        raise ConfigError("pauses must not be negative")
    if config.backfill.pause_between_chats_sec < 0:
        raise ConfigError("[backfill] pause_between_chats_sec must not be negative")


def load_config(path: Path) -> Config:
    """Read `config.toml`; a missing file means defaults."""
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    return parse_config(data)
