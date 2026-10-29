"""Safe, comment-preserving edit of `config.toml`."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from chatimport.config import ConfigError, parse_config
from chatimport.storage.state import atomic_write_bytes

_SECTION_RE = re.compile(r"^\s*\[\s*output\s*\]\s*(#.*)?$")
_TABLE_RE = re.compile(r"^\s*\[")
_ROOT_KEY_RE = re.compile(r"^\s*root_dir\s*=")
_KEY_RE = re.compile(r"^\s*[A-Za-z0-9_-]+\s*=")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\u007f")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error


def _edited(text: str, root: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    assignment = f"root_dir = {_toml_string(root)}{newline}"
    lines = text.splitlines(keepends=True)
    start = next((n for n, line in enumerate(lines) if _SECTION_RE.match(line.rstrip("\r\n"))), -1)
    if start < 0:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        return "".join([*lines, f"[output]{newline}", assignment])
    end = len(lines)
    for number in range(start + 1, len(lines)):
        if _TABLE_RE.match(lines[number]):
            end = number
            break
    last_key = start
    for number in range(start + 1, end):
        if _ROOT_KEY_RE.match(lines[number]):
            lines[number] = assignment
            return "".join(lines)
        if _KEY_RE.match(lines[number]):
            last_key = number
    if not lines[last_key].endswith("\n"):
        lines[last_key] += newline
    lines.insert(last_key + 1, assignment)
    return "".join(lines)


def set_output_root(config_file: Path | str, root: Path | str) -> None:
    """Set `[output] root_dir`, keeping comments and every other setting."""
    path = Path(config_file)
    new_text = _edited(_read(path), str(root))
    try:
        data = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"cannot update {path}: {error}") from error
    parse_config(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, new_text.encode("utf-8"))
