"""Safe, comment-preserving edit of `config.toml`."""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from chatimport.config import ConfigError, parse_config
from chatimport.storage.fileio import PRIVATE_FILE_MODE
from chatimport.toml_edit import TomlDocument, toml_string, write_validated

type ConfigValue = str | int | float | bool | Sequence[str]

_NAME_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error


def _literal(value: ConfigValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigError("a number must be finite")
        return repr(value)
    if isinstance(value, str):
        return toml_string(value)
    return "[" + ", ".join(toml_string(item) for item in value) + "]"


def _header(section: str) -> re.Pattern[str]:
    if _NAME_RE.fullmatch(section) is None:
        raise ConfigError(f"invalid section name: {section!r}")
    return re.compile(rf"^\s*\[\s*{section}\s*\]\s*(#.*)?$")


def _edited(text: str, changes: Mapping[str, Mapping[str, ConfigValue]]) -> str:
    document = TomlDocument(text)
    for section, values in changes.items():
        if not values:
            continue
        literals = {key: _literal(value) for key, value in values.items()}
        for key in literals:
            if _NAME_RE.fullmatch(key) is None:
                raise ConfigError(f"invalid key name: {key!r}")
        tables = document.find_tables(_header(section))
        if not tables:
            document.append_block([f"[{section}]"])
            tables = document.find_tables(_header(section))
        for key, literal in literals.items():
            document.set_value(tables[0], key, literal)
    return document.text()


def _validate(path: Path, text: str) -> None:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"cannot update {path}: {error}") from error
    parse_config(data)


def update_config(
    config_file: Path | str, changes: Mapping[str, Mapping[str, ConfigValue]]
) -> None:
    """Set keys in sections of `config.toml`, keeping comments and every other setting.

    The result is parsed with `parse_config` before the atomic write, so an invalid value
    raises `ConfigError` and leaves the file as it was. The file holds the Telegram api_hash,
    so on POSIX it is written owner-only.
    """
    path = Path(config_file)
    write_validated(
        path,
        _edited(_read(path), changes),
        lambda text: _validate(path, text),
        mode=PRIVATE_FILE_MODE,
    )


def set_output_root(config_file: Path | str, root: Path | str) -> None:
    """Set `[output] root_dir`."""
    update_config(config_file, {"output": {"root_dir": str(root)}})
