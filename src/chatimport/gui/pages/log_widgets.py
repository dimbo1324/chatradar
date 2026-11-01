"""Small pieces of the Log page: a labelled switch, the detail pane and a floating-button host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.pages.log_delegate import mono_font
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.switch import Switch

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent, QResizeEvent

    from chatimport.gui.kit import UiKit
    from chatimport.gui.models.log_parser import LogRecord
    from chatimport.gui.widgets.button import Button


class InlineSwitch(QWidget):
    """A switch with its label beside it; clicking the label toggles too."""

    toggled = Signal(bool)

    def __init__(self, kit: UiKit, text: str = "", *, checked: bool = False) -> None:
        super().__init__()
        self.switch = Switch(kit, checked=checked)
        self._label = QLabel(text)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.addWidget(self.switch)
        self._row.addWidget(self._label)
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.installEventFilter(self)
        self.switch.toggled.connect(self.toggled)
        self.switch.setAccessibleName(text)
        bind_kit(kit, zoom=lambda: self._row.setSpacing(kit.px(SPACE[3])))
        self._row.setSpacing(kit.px(SPACE[3]))

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.switch.setChecked(checked)

    def set_text(self, text: str, tip: str = "") -> None:
        self._label.setText(text)
        self.switch.setAccessibleName(text)
        self.setToolTip(tip)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._label and event.type() == QEvent.Type.MouseButtonRelease:
            mouse: QMouseEvent = event  # pyright: ignore[reportAssignmentType]
            if mouse.button() == Qt.MouseButton.LeftButton:
                self.switch.toggle()
                return True
        return super().eventFilter(watched, event)  # pyright: ignore[reportArgumentType]


class DetailPane(QPlainTextEdit):
    """The whole selected record, traceback included: selectable, monospace, optionally wrapped."""

    def __init__(self, kit: UiKit) -> None:
        super().__init__()
        self.kit = kit
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setAccessibleName(tr("log.detail.label"))
        bind_kit(kit, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()

    def show_record(self, record: LogRecord | None) -> None:
        self.setPlainText("" if record is None else record.as_text())

    def set_wrap(self, wrap: bool) -> None:
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth if wrap else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.setLineWrapMode(mode)

    def _restyle(self) -> None:
        self.setFont(mono_font(self.font(), self.kit))

    def _retranslate(self) -> None:
        self.setPlaceholderText(tr("log.detail.empty"))
        self.setAccessibleName(tr("log.detail.label"))


class FloatingHost(QWidget):
    """Holds a child and keeps a pill button pinned to its bottom-right corner."""

    def __init__(self, kit: UiKit, child: QWidget, floating: Button) -> None:
        super().__init__()
        self.kit = kit
        self._floating = floating
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(child)
        floating.setParent(self)
        floating.raise_()
        floating.hide()

    def place(self) -> None:
        margin = self.kit.px(SPACE[6])
        self._floating.adjustSize()
        self._floating.move(
            self.width() - self._floating.width() - margin,
            self.height() - self._floating.height() - margin,
        )
        self._floating.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.place()
