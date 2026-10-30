from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import TYPE_CHECKING

import pytest

from chatimport.logging_setup import (
    BACKUP_COUNT,
    LOG_FILE,
    MAX_BYTES,
    ExtraFormatter,
    configure_logging,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

CYRILLIC = "".join(map(chr, (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442)))


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    quiet = {name: logging.getLogger(name).level for name in ("telethon", "asyncio")}
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
    for name, value in quiet.items():
        logging.getLogger(name).setLevel(value)


def owned(kind: type[logging.Handler]) -> list[logging.Handler]:
    """Handlers installed by `configure_logging`; a file handler is not counted as a stream."""
    return [
        h
        for h in logging.getLogger().handlers
        if type(h).__module__ == "chatimport.logging_setup"
        and isinstance(h, kind)
        and (kind is not logging.StreamHandler or not isinstance(h, logging.FileHandler))
    ]


def test_file_log_rotates_is_utf8_and_carries_the_extras(tmp_path: Path) -> None:
    configure_logging(tmp_path / "logs", console=False)
    logging.getLogger("chatimport.test").warning(
        "x %s", CYRILLIC, extra={"chat_id": 5, "part": "2026-10_001"}
    )
    (handler,) = owned(logging.handlers.RotatingFileHandler)
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    handler.flush()
    assert handler.maxBytes == MAX_BYTES > 0
    assert handler.backupCount == BACKUP_COUNT
    text = (tmp_path / "logs" / LOG_FILE).read_text(encoding="utf-8")
    assert f"WARNING chatimport.test: x {CYRILLIC} chat_id=5 part=2026-10_001" in text
    assert "Z WARNING" in text


def test_calling_twice_replaces_the_handlers_instead_of_adding(tmp_path: Path) -> None:
    configure_logging(tmp_path, console=True)
    configure_logging(tmp_path, console=True, level="debug")
    assert len(owned(logging.handlers.RotatingFileHandler)) == 1
    assert len(owned(logging.StreamHandler)) == 1
    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("telethon").level == logging.WARNING


def test_console_only_and_no_console_under_pythonw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_logging(None, console=True)
    assert owned(logging.handlers.RotatingFileHandler) == []
    assert len(owned(logging.StreamHandler)) == 1
    monkeypatch.setattr(sys, "stderr", None)
    configure_logging(None, console=True)
    assert owned(logging.StreamHandler) == []
    assert not (tmp_path / LOG_FILE).exists()


def test_formatter_without_extras_and_with_a_traceback() -> None:
    formatter = ExtraFormatter()
    plain = logging.makeLogRecord({"msg": "hello", "levelname": "INFO", "name": "n"})
    assert formatter.format(plain).endswith("INFO n: hello")
    try:
        raise ValueError("boom")
    except ValueError:
        failed = logging.makeLogRecord(
            {"msg": "bad", "levelname": "ERROR", "name": "n", "exc_info": sys.exc_info(), "x": 1}
        )
    head, _, rest = formatter.format(failed).partition("\n")
    assert head.endswith("ERROR n: bad x=1")
    assert "ValueError: boom" in rest
