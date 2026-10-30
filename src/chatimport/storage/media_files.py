"""The media file naming rule: `media/<YYYY-MM>/<msg_id>[_<n>]<ext>`.

The name starts with the message id, because trimming deletes the media of the messages it
removes. A file keeps the extension Telegram gave it only when that extension is harmless for
its media type; anything else (`.exe`, `.lnk`, `.hta`, ...) gets `.bin` appended, so a
double click never runs it. On Windows each file is marked as downloaded from the internet.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from chatimport.storage.layout import MEDIA_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)

NEUTRAL_SUFFIX: Final = ".bin"
MARK_OF_THE_WEB: bool = sys.platform == "win32"
ZONE_IDENTIFIER: Final = b"[ZoneTransfer]\r\nZoneId=3\r\n"

_PICTURES: Final = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_SOUNDS: Final = frozenset({".ogg", ".oga", ".opus", ".mp3", ".m4a", ".flac", ".wav"})
_MOVIES: Final = frozenset({".mp4", ".mov", ".webm", ".mkv"})
SAFE_SUFFIXES: Final[dict[str, frozenset[str]]] = {
    "photo": _PICTURES,
    "sticker": frozenset({".webp", ".webm", ".tgs"}),
    "voice": _SOUNDS,
    "audio": _SOUNDS,
    "video_note": _MOVIES,
    "video": _MOVIES,
    "document": _PICTURES
    | _SOUNDS
    | _MOVIES
    | frozenset({".pdf", ".txt", ".csv", ".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods"}),
}


def media_month_dir(folder: Path, month: str) -> Path:
    return folder / MEDIA_DIR / month


def safe_suffix(suffix: str, media_type: str) -> str:
    """`suffix` when it is harmless for `media_type`, else `suffix` plus `.bin`."""
    lowered = suffix.lower()
    if not suffix or lowered == NEUTRAL_SUFFIX or lowered in SAFE_SUFFIXES.get(media_type, ()):
        return suffix
    return f"{suffix}{NEUTRAL_SUFFIX}"


def media_file_name(msg_id: int, suffix: str, number: int = 0) -> str:
    stem = str(msg_id) if number == 0 else f"{msg_id}_{number}"
    return f"{stem}{suffix}"


def media_msg_id(name: str) -> int | None:
    """The message id a media file name starts with, or None for a foreign file."""
    digits = name.split(".", 1)[0].split("_", 1)[0]
    return int(digits) if digits.isdecimal() else None


def unique_media_path(downloaded: Path, msg_id: int, media_type: str) -> Path:
    """`<msg_id><ext>`, or `<msg_id>_<n><ext>` when that name is taken by another file."""
    suffix = safe_suffix(downloaded.suffix, media_type)
    number = 0
    while True:
        candidate = downloaded.with_name(media_file_name(msg_id, suffix, number))
        if candidate == downloaded or not candidate.exists():
            return candidate
        number += 1


def mark_downloaded(path: Path) -> None:
    """Windows: attach the Internet zone, so Explorer warns before opening the file. Volumes
    without alternate data streams (FAT, network shares) silently do without."""
    if not MARK_OF_THE_WEB:
        return
    with (
        contextlib.suppress(OSError),
        Path(f"{path}:Zone.Identifier").open("wb") as stream,
    ):
        stream.write(ZONE_IDENTIFIER)


def delete_media(folder: Path, month: str, msg_ids: Iterable[int]) -> None:
    """Delete the media files of `msg_ids` in one month folder, then the folder if empty."""
    wanted = set(msg_ids)
    month_dir = media_month_dir(folder, month)
    if not wanted or not month_dir.is_dir():
        return
    for entry in month_dir.iterdir():
        if entry.is_file() and media_msg_id(entry.name) in wanted:
            try:
                entry.unlink()
            except OSError:
                log.warning("cannot delete a media file", extra={"folder": folder.name})
    if not any(month_dir.iterdir()):
        try:
            month_dir.rmdir()
        except OSError:
            log.warning("cannot remove an empty media folder", extra={"folder": folder.name})
