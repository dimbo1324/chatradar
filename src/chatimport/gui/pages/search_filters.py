"""Filter and status widgets of the Search page: the chat picker and the index status strip."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from chatimport.gui.format import format_count, format_percent
from chatimport.gui.i18n import plural, tr
from chatimport.gui.pages.search_parts import StickyMenu
from chatimport.gui.strings import current_language
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.progress import ProgressBar
from chatimport.search_types import IndexState

if TYPE_CHECKING:
    from PySide6.QtGui import QAction

    from chatimport.gui.kit import UiKit
    from chatimport.search_types import ChatChoice, IndexStatus


PROGRESS_WIDTH: Final = 96


class ChatFilter(QObject):
    """A button with a multi-select menu of chats; nothing selected means every chat."""

    changed = Signal()

    def __init__(self, kit: UiKit, parent: QWidget) -> None:
        super().__init__(parent)
        self.button = Button(kit, "", icon_name="chevron-down")
        self.menu = StickyMenu(parent)
        self._chats: tuple[ChatChoice, ...] = ()
        self._built: tuple[ChatChoice, ...] | None = None
        self._selected: set[int] = set()
        self._actions: dict[int, QAction] = {}
        self._all: QAction | None = None
        self.button.clicked.connect(self._popup)
        self.refresh()

    @property
    def selected(self) -> frozenset[int]:
        return frozenset(self._selected)

    def set_chats(self, chats: tuple[ChatChoice, ...]) -> None:
        self._chats = chats
        self._selected &= {choice.chat_id for choice in chats}
        self.refresh()

    def retranslate(self) -> None:
        self._built = None
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the menu when the chats or the language changed, then show the selection."""
        if self._built != self._chats or self._all is None:
            self._build()
        self._sync()

    def _build(self) -> None:
        self._built = self._chats
        self.menu.clear()
        self._actions.clear()
        language = current_language()
        self._all = self.menu.addAction(tr("find.chats.menu_all"))
        self._all.setCheckable(True)
        self._all.toggled.connect(self._on_all)
        self.menu.addSeparator()
        if not self._chats:
            self.menu.addAction(tr("find.chats.none")).setEnabled(False)
        for choice in self._chats:
            action = self.menu.addAction(
                f"{choice.title}  ({format_count(choice.messages, language)})"
            )
            action.setCheckable(True)
            action.toggled.connect(partial(self._on_chat, choice.chat_id))
            self._actions[choice.chat_id] = action

    def _sync(self) -> None:
        if self._all is not None:
            self._check(self._all, not self._selected)
        for chat_id, action in self._actions.items():
            self._check(action, chat_id in self._selected)
        chosen = [choice for choice in self._chats if choice.chat_id in self._selected]
        if not chosen:
            text = tr("find.chats.all")
        elif len(chosen) == 1:
            text = chosen[0].title
        else:
            text = plural(len(chosen), "find.chats.some")
        self.button.setText(text)
        self.button.setToolTip(tr("find.chats.tip"))
        self.button.setEnabled(bool(self._chats))

    @staticmethod
    def _check(action: QAction, checked: bool) -> None:
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _on_all(self, _on: bool) -> None:
        self._selected.clear()
        self._sync()
        self.changed.emit()

    def _on_chat(self, chat_id: int, on: bool) -> None:
        if on:
            self._selected.add(chat_id)
        else:
            self._selected.discard(chat_id)
        self._sync()
        self.changed.emit()

    def _popup(self) -> None:
        self.menu.popup(self.button.mapToGlobal(QPoint(0, self.button.height())))


class StatusStrip(QWidget):
    """ "Indexing 47%" with a thin bar while building, otherwise a one-line index summary."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLabel()
        set_role(self.label, "muted")
        self.progress = ProgressBar(kit, tone="accent")
        self.progress.hide()
        self._kit = kit
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.progress)
        row.addWidget(self.label)
        bind_kit(kit, zoom=self._resize)
        self._resize()

    def _resize(self) -> None:
        self.progress.setFixedWidth(self._kit.px(PROGRESS_WIDTH))

    def show_state(self, state: IndexState | None, status: IndexStatus | None) -> bool:
        """Show the index state; returns whether it is still changing (BUILDING or MISSING)."""
        language = current_language()
        building = state is IndexState.BUILDING and status is not None
        tip = ""
        if state is IndexState.DISABLED:
            text = tr("find.status.disabled")
        elif state is IndexState.MISSING:
            text = tr("find.status.missing")
        elif state is None or status is None:
            text = tr("find.status.unknown")
        elif state is IndexState.BUILDING:
            fraction = status.indexed / status.total if status.total else None
            text = tr("find.status.building", percent=format_percent(fraction or 0.0, language))
            self.progress.set_value(fraction)
            tip = tr(
                "find.status.building_tip",
                indexed=format_count(status.indexed, language),
                total=format_count(status.total, language),
            )
        else:
            count = format_count(status.indexed, language)
            text = plural(status.indexed, "find.status.ready", n=count)
        self.label.setText(text)
        self.label.setToolTip(tip)
        self.progress.setVisible(building)
        return building or state is IndexState.MISSING
