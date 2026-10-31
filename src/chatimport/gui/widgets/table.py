"""House settings for a `QTableView`: left-aligned header, token row height, no grid or numbers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from chatimport.gui.widgets.base import bind_kit

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit

ROW_HEIGHT = 36
HEADER_HEIGHT = 32


def configure_table(view: QTableView, kit: UiKit) -> None:
    """Apply the table look; row and header heights follow the zoom."""
    view.setShowGrid(False)
    view.setAlternatingRowColors(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalHeader().setVisible(False)
    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(True)

    def apply() -> None:
        view.verticalHeader().setDefaultSectionSize(kit.px(ROW_HEIGHT))
        header.setFixedHeight(kit.px(HEADER_HEIGHT))

    bind_kit(kit, zoom=apply)
    apply()
