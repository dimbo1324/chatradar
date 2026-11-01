"""Building blocks of the Settings cards: a card shell, labelled rows and small value editors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import Tone, bind_kit, set_role
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.card import Card
from chatimport.gui.widgets.labels import make_label

if TYPE_CHECKING:
    from PySide6.QtGui import QResizeEvent

    from chatimport.gui.kit import UiKit
    from chatimport.gui.widgets.button import Button

EDITOR_WIDTH: Final = 128
WIDE_EDITOR_WIDTH: Final = 220


def divider() -> QFrame:
    line = QFrame()
    set_role(line, "divider")
    return line


class FieldRow(QWidget):
    """Label and hint on the left, the editor on the right."""

    def __init__(
        self,
        kit: UiKit,
        editor: QWidget,
        *,
        label: str = "",
        hint: str = "",
        editor_width: int | None = EDITOR_WIDTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.editor = editor
        self._editor_width = editor_width
        self._label = QLabel(label)
        self._label.setWordWrap(True)
        self._hint = make_label(hint, "caption", wrap=True)
        self._hint.setVisible(bool(hint))
        self._texts = QVBoxLayout()
        self._texts.setContentsMargins(0, 0, 0, 0)
        self._texts.addWidget(self._label)
        self._texts.addWidget(self._hint)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.addLayout(self._texts, 1)
        self._row.addWidget(editor, 0, Qt.AlignmentFlag.AlignTop)
        bind_kit(kit, zoom=self._restyle)
        self._restyle()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        for label in (self._label, self._hint):
            needed = label.heightForWidth(label.width())
            if needed > 0 and needed != label.minimumHeight():
                label.setMinimumHeight(needed)

    def set_texts(self, label: str, hint: str = "") -> None:
        self._label.setText(label)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))
        self.editor.setAccessibleName(label)

    def _restyle(self) -> None:
        self._texts.setSpacing(self.kit.px(SPACE[1]))
        self._row.setSpacing(self.kit.px(SPACE[6]))
        if self._editor_width is not None:
            self.editor.setFixedWidth(self.kit.px(self._editor_width))


class SettingsCard(Card):
    """A titled card: header, rows, an inline message and an optional footer."""

    def __init__(self, kit: UiKit, key: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(kit, parent=parent)
        self.key = key
        self._icon_name = icon_name
        self.setObjectName(f"SettingsCard_{key}")
        self._icon = QLabel()
        self._title = make_label("", "section")
        self._lede = make_label("", "muted", wrap=True)
        self._head = QHBoxLayout()
        self._head.addWidget(self._icon)
        self._head.addWidget(self._title, 1)
        self.body.addLayout(self._head)
        self.body.addWidget(self._lede)
        self._lede.hide()
        self.message = Callout(kit, "info", "")
        self.message.hide()
        self._footer = QHBoxLayout()
        self._status = make_label("", "caption")
        self._footer.addWidget(self._status, 1)
        self.body.addWidget(self.message)
        self.body.addLayout(self._footer)
        self._added: list[QWidget] = []
        bind_kit(kit, theme=self._restyle_icon, zoom=self._restyle_icon)
        self._restyle_icon()

    def set_texts(self, title: str, lede: str = "") -> None:
        self._title.setText(title)
        self._lede.setText(lede)
        self._lede.setVisible(bool(lede))

    def add_row(self, row: QWidget) -> None:
        if self._added:
            self._insert(divider())
        self._insert(row)
        self._added.append(row)

    def add_plain(self, widget: QWidget) -> None:
        self._insert(widget)

    def add_footer_button(self, button: Button) -> None:
        self._footer.addWidget(button)

    def _insert(self, widget: QWidget) -> None:
        self.body.insertWidget(self.body.indexOf(self.message), widget)

    def show_message(self, tone: Tone, body: str, title: str = "") -> None:
        self.message.set_tone(tone)
        self.message.set_title(title)
        self.message.set_body(body)
        self.message.show()

    def clear_message(self) -> None:
        self.message.hide()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def _restyle_icon(self) -> None:
        size = self.kit.px(LAYOUT["icon_lg"])
        self._icon.setPixmap(icon_pixmap(self._icon_name, self.kit.palette.accent_fg, size))
        self._head.setSpacing(self.kit.px(SPACE[4]))


class TimeEdit(QWidget):
    """Hours and minutes as two spin boxes; the value is `HH:MM`."""

    changed = Signal()

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self._hours = QSpinBox()
        self._hours.setRange(0, 23)
        self._hours.setWrapping(True)
        self._hours.setAccessibleName("HH")
        self._minutes = QSpinBox()
        self._minutes.setRange(0, 59)
        self._minutes.setWrapping(True)
        self._minutes.setAccessibleName("MM")
        for spin in (self._hours, self._minutes):
            spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.valueChanged.connect(self.changed)
        self._colon = QLabel(":")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(kit.px(SPACE[2]))
        row.addWidget(self._hours, 1)
        row.addWidget(self._colon)
        row.addWidget(self._minutes, 1)

    @property
    def text(self) -> str:
        return f"{self._hours.value():02d}:{self._minutes.value():02d}"

    def set_text(self, value: str) -> None:
        hours, _, minutes = value.partition(":")
        self._hours.setValue(int(hours) if hours.isdigit() else 0)
        self._minutes.setValue(int(minutes) if minutes.isdigit() else 0)

    def setAccessibleName(self, name: str) -> None:
        super().setAccessibleName(name)
        self._hours.setAccessibleName(f"{name} (h)")
        self._minutes.setAccessibleName(f"{name} (min)")
