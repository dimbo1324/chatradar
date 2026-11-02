from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance


def record(signal: SignalInstance, log: list[Any], tag: object = None) -> None:
    """Append `tag` (or the emitted arguments when no tag is given) on every emission."""

    def slot(*args: Any) -> None:
        log.append(args if tag is None else tag)

    signal.connect(slot)
