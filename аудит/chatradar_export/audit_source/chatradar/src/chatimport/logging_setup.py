"""Process-wide logging: a bounded rotating UTF-8 file in the log folder and/or the console.

Log lines carry ids, counts and sizes passed through `extra=`; they never carry message text,
sender names or invite hashes (the callers' rule, not something this module can check).
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from pathlib import Path

LOG_FILE: Final = "chatimport.log"
MAX_BYTES: Final = 5 * 1024 * 1024
BACKUP_COUNT: Final = 5
QUIET_LOGGERS: Final = ("telethon", "asyncio")

_STANDARD_FIELDS: Final = frozenset(
    {*vars(logging.makeLogRecord({})), "message", "asctime", "taskName"}
)


class ExtraFormatter(logging.Formatter):
    """The usual line plus every `extra=` field as ` key=value`, in name order."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        moment = datetime.fromtimestamp(record.created, UTC)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @override
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        extras = sorted(
            (key, value) for key, value in vars(record).items() if key not in _STANDARD_FIELDS
        )
        if not extras:
            return text
        head, newline, rest = text.partition("\n")
        suffix = " ".join(f"{key}={value}" for key, value in extras)
        return f"{head} {suffix}{newline}{rest}"


class _OwnedFileHandler(logging.handlers.RotatingFileHandler):
    """Marks the handlers this module installed, so a second call can replace them."""


class _OwnedStreamHandler(logging.StreamHandler):  # pyright: ignore[reportMissingTypeArgument]
    """Marks the handlers this module installed, so a second call can replace them."""


def configure_logging(log_dir: Path | None, *, console: bool, level: str = "INFO") -> None:
    """Install the file handler (when `log_dir` is given) and the console handler; calling it
    again replaces the earlier ones instead of adding duplicates."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, _OwnedFileHandler | _OwnedStreamHandler):
            root.removeHandler(handler)
            handler.close()
    formatter = ExtraFormatter()
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = _OwnedFileHandler(
            log_dir / LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    if console and sys.stderr is not None:  # pyright: ignore[reportUnnecessaryComparison]
        stream_handler = _OwnedStreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    root.setLevel(level.upper())
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))
