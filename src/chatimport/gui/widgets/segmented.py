"""A segmented control: one choice from a few options, arrow-key navigable.

An option can be marked unavailable: it stays clickable and focusable, dimmed, and clicking it
explains why instead of selecting it. The active option's hint (or that explanation) shows
under the track.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from chatimport.gui.icons import icon
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit, set_property

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent

    from chatimport.gui.kit import UiKit


@dataclass(frozen=True, slots=True)
class SegmentOption:
    value: str
    label: str
    hint: str = ""
    unavailable: str = ""
    icon: str | None = None
    tooltip: str = ""


class _OptionButton(QPushButton):
    def __init__(self, owner: Segmented, index: int, option: SegmentOption) -> None:
        super().__init__(option.label)
        self._owner = owner
        self._index = index
        self.setObjectName("SegmentedOption")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(lambda: owner.choose(index))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = {
            Qt.Key.Key_Right: 1,
            Qt.Key.Key_Down: 1,
            Qt.Key.Key_Left: -1,
            Qt.Key.Key_Up: -1,
        }.get(Qt.Key(event.key()), 0)
        if step:
            self._owner.step_focus(self._index, step)
            event.accept()
        else:
            super().keyPressEvent(event)


class Segmented(QWidget):
    selected = Signal(str)

    def __init__(
        self,
        kit: UiKit,
        options: list[SegmentOption],
        value: str,
        *,
        label: str = "",
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self._compact = compact
        self._options: list[SegmentOption] = []
        self._buttons: list[_OptionButton] = []
        self._value = value
        self._note = ""
        self._label = QLabel(label)
        self._label.setVisible(bool(label))
        self._track = QFrame()
        self._track.setObjectName("SegmentedTrack")
        self._row = QHBoxLayout(self._track)
        self._caption = QLabel()
        self._caption.setObjectName("SegmentedNote")
        self._caption.setWordWrap(True)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.addWidget(self._label)
        self._column.addWidget(self._track)
        self._column.addWidget(self._caption)
        self.setAccessibleName(label)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle)
        self.set_options(options, value)

    @property
    def value(self) -> str:
        return self._value

    def set_label(self, label: str) -> None:
        self._label.setText(label)
        self._label.setVisible(bool(label))
        self.setAccessibleName(label)

    def set_options(self, options: list[SegmentOption], value: str | None = None) -> None:
        """Replace the options (for example after a language change); keeps the value."""
        for button in self._buttons:
            self._row.removeWidget(button)
            button.deleteLater()
        self._options = options
        if value is not None:
            self._value = value
        self._buttons = [_OptionButton(self, i, option) for i, option in enumerate(options)]
        for button in self._buttons:
            self._row.addWidget(button, 1)
        self._note = ""
        self._restyle()

    def set_value(self, value: str) -> None:
        self._value = value
        self._note = ""
        self._restyle()

    def choose(self, index: int) -> None:
        option = self._options[index]
        if option.unavailable:
            self._note = option.unavailable
            self._restyle()
            self._buttons[index].setFocus()
            return
        self._note = ""
        changed = option.value != self._value
        self._value = option.value
        self._restyle()
        if changed:
            self.selected.emit(option.value)

    def step_focus(self, index: int, step: int) -> None:
        target = (index + step) % len(self._buttons)
        self.choose(target)
        self._buttons[target].setFocus(Qt.FocusReason.TabFocusReason)

    def _restyle(self) -> None:
        px = self.kit.px
        pad = px(3)
        self._row.setContentsMargins(pad, pad, pad, pad)
        self._row.setSpacing(px(SPACE[1]))
        self._column.setSpacing(px(SPACE[3]))
        height = px(LAYOUT["control"] - 8 if self._compact else LAYOUT["control"] - 6)
        palette = self.kit.palette
        size = px(LAYOUT["icon_md"] - (2 if self._compact else 0))
        active = self._value
        for option, button in zip(self._options, self._buttons, strict=True):
            is_active = option.value == active
            button.setFixedHeight(height)
            button.setChecked(is_active)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus if is_active else Qt.FocusPolicy.NoFocus)
            set_property(button, "unavailable", bool(option.unavailable))
            set_property(button, "compact", self._compact)
            tip = option.tooltip or option.unavailable
            button.setToolTip(tip)
            button.setAccessibleName(option.label or option.tooltip)
            button.setText(option.label)
            if option.icon:
                color = palette.fg if is_active else palette.fg_muted
                button.setIcon(icon(option.icon, color, size))
                button.setIconSize(QSize(size, size))
            if not option.label:
                button.setFixedWidth(px(LAYOUT["control"] + 2))
        active_option = next((o for o in self._options if o.value == active), None)
        text = self._note or (active_option.hint if active_option else "")
        self._caption.setText(text)
        self._caption.setVisible(bool(text))
