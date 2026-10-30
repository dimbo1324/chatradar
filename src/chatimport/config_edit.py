"""Safe, comment-preserving edit of `config.toml`."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Final

from chatimport.config import ConfigError, parse_config
from chatimport.storage.fileio import PRIVATE_FILE_MODE
from chatimport.toml_edit import TomlDocument, toml_string, write_validated

_SECTION_RE: Final = re.compile(r"^\s*\[\s*output\s*\]\s*(#.*)?$")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error


def _edited(text: str, root: str) -> str:
    document = TomlDocument(text)
    value = toml_string(root)
    sections = document.find_tables(_SECTION_RE)
    if sections:
        document.set_value(sections[0], "root_dir", value)
    else:
        document.append_block(["[output]", f"root_dir = {value}"])
    return document.text()


def _validate(path: Path, text: str) -> None:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"cannot update {path}: {error}") from error
    parse_config(data)


def set_output_root(config_file: Path | str, root: Path | str) -> None:
    """Set `[output] root_dir`, keeping comments and every other setting. The file holds the
    Telegram api_hash, so on POSIX it is written owner-only."""
    path = Path(config_file)
    write_validated(
        path,
        _edited(_read(path), str(root)),
        lambda text: _validate(path, text),
        mode=PRIVATE_FILE_MODE,
    )
