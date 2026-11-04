"""Widgets of one test must not linger: every theme or zoom change restyles all live widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def drop_top_level_widgets(qapp: QApplication) -> Iterator[None]:
    yield
    for widget in QApplication.topLevelWidgets():
        if shiboken6.isValid(widget):
            widget.hide()
            shiboken6.delete(widget)
    qapp.processEvents()
