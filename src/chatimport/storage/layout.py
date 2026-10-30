"""On-disk layout of the chat data root (spec §5.2): folders, part names, discovery."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

STATE_FILE: Final = "state.json"
SERVICE_PREFIX: Final = "_"

_PART_RE: Final = re.compile(r"([0-9]{4}-(?:0[1-9]|1[0-2]))_((?!000)[0-9]{3})\.jsonl")
_UNSAFE_RE: Final = re.compile(r"[^a-z0-9_-]+")
_REPEAT_RE: Final = re.compile(r"_{2,}")
_SLUG_MAX: Final = 40
_SLUG_FALLBACK: Final = "chat"
MAX_PART_NUMBER: Final = 999


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = _UNSAFE_RE.sub("_", ascii_name.lower())
    slug = _REPEAT_RE.sub("_", slug)[:_SLUG_MAX].strip("_-")
    return slug or _SLUG_FALLBACK


def chat_folder_name(name: str, chat_id: int) -> str:
    return f"{slugify(name)}_{chat_id}"


def month_key(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m")


def part_file_name(month: str, part: int) -> str:
    return f"{month}_{part:03d}.jsonl"


def part_key(month: str, part: int) -> str:
    return f"{month}_{part:03d}"


def parse_part_name(name: str) -> tuple[str, int] | None:
    match = _PART_RE.fullmatch(name)
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def list_parts(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    parts = [p for p in folder.iterdir() if p.is_file() and parse_part_name(p.name) is not None]
    return sorted(parts, key=lambda p: p.name)


def iter_chat_folders(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and not entry.name.startswith(SERVICE_PREFIX):
            yield entry


def find_chat_folder(root: Path, chat_id: int) -> Path | None:
    from chatimport.storage.state import load_state

    suffix = f"_{chat_id}"
    fallback: Path | None = None
    for folder in iter_chat_folders(root):
        state = load_state(folder)
        if state is None:
            if fallback is None and folder.name.endswith(suffix):
                fallback = folder
        elif state.chat_id == chat_id:
            return folder
    return fallback
