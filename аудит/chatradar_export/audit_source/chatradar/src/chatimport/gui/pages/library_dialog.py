"""The chat library dialog: list, enable switches and "add a chat", over `chats.toml`.

The file is edited through `library.add_entry` / `set_enabled` (the same code as the CLI), and
the running service rereads it within about 10 seconds. Invite links are shown masked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.i18n import tr
from chatimport.gui.locales import chats as _chat_strings
from chatimport.gui.pages.support import clear_layout
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import ElidedLabel, make_label
from chatimport.gui.widgets.switch import Switch
from chatimport.library import ChatEntry, LibraryError, add_entry, load_library, set_enabled
from chatimport.refs import display_ref
from chatimport.resolution import resolve_error_key

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chatimport.gui.context import GuiContext
    from chatimport.gui.models.snapshot import ServiceError

_ = _chat_strings
DIALOG_WIDTH = 560
LIST_HEIGHT = 260


class _EntryRow(QFrame):
    def __init__(self, dialog: LibraryDialog, entry: ChatEntry, unresolved: bool) -> None:
        super().__init__()
        self.setObjectName("LibraryRow")
        self._entry = entry
        kit = dialog.gui.kit
        self._switch = Switch(kit, checked=entry.enabled)
        self._switch.setAccessibleName(tr("chats.lib.enabled"))
        self._switch.setToolTip(tr("chats.lib.enabled"))
        self._switch.toggled.connect(self._on_toggled)
        self._dialog = dialog
        name = entry.name or tr("chats.lib.unnamed")
        title = ElidedLabel(name)
        subtitle = ElidedLabel(display_ref(entry.key), "muted")
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        texts.addWidget(title)
        texts.addWidget(subtitle)
        row = QHBoxLayout(self)
        row.setContentsMargins(
            kit.px(SPACE[5]), kit.px(SPACE[3]), kit.px(SPACE[5]), kit.px(SPACE[3])
        )
        row.addLayout(texts, 1)
        if unresolved:
            row.addWidget(Chip(kit, tr("chats.lib.unresolved"), "danger", icon_name="alert"))
        row.addWidget(self._switch)

    def _on_toggled(self, checked: bool) -> None:
        self._dialog.toggle(self._entry, checked)


class LibraryDialog(QDialog):
    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        self._errors: Sequence[ServiceError] = ()
        self.setMinimumWidth(gui.zoom.scaled(DIALOG_WIDTH))
        self._lede = make_label("", "muted", wrap=True)
        self._list_host = QWidget()
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(gui.zoom.scaled(SPACE[2]))
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._list_host)
        self._scroll.setMinimumHeight(gui.zoom.scaled(LIST_HEIGHT))
        self._add_title = make_label("", "section")
        self._ref = QLineEdit()
        self._name = QLineEdit()
        self._add = Button(gui.kit, "", variant="primary", icon_name="plus")
        self._add.clicked.connect(self._on_add)
        self._ref.returnPressed.connect(self._on_add)
        self._problem = Callout(gui.kit, "danger", "")
        self._problem.hide()
        self._close = Button(gui.kit, "")
        self._close.clicked.connect(self.accept)
        form = QHBoxLayout()
        form.addWidget(self._ref, 3)
        form.addWidget(self._name, 2)
        form.addWidget(self._add)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self._close)
        column = QVBoxLayout(self)
        gap = gui.zoom.scaled(SPACE[5])
        column.setContentsMargins(gap, gap, gap, gap)
        column.setSpacing(gap)
        column.addWidget(self._lede)
        column.addWidget(self._scroll, 1)
        column.addWidget(self._add_title)
        column.addLayout(form)
        column.addWidget(self._problem)
        column.addLayout(footer)
        bind_kit(gui.kit, language=self._retranslate)
        self._retranslate()
        self.reload()

    def set_errors(self, errors: Sequence[ServiceError]) -> None:
        self._errors = errors
        self.reload()

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("chats.lib.title"))
        self._lede.setText(tr("chats.lib.lede"))
        self._add_title.setText(tr("chats.lib.add_title"))
        self._ref.setPlaceholderText(tr("chats.lib.ref"))
        self._ref.setAccessibleName(tr("chats.lib.ref"))
        self._name.setPlaceholderText(tr("chats.lib.name"))
        self._name.setAccessibleName(tr("chats.lib.name"))
        self._add.setText(tr("chats.lib.add"))
        self._close.setText(tr("common.close"))
        self.reload()

    def reload(self) -> None:
        clear_layout(self._list)
        try:
            entries = load_library(self.gui.service.library_file).entries
        except LibraryError as error:
            self._show_problem(tr("chats.lib.error_read", detail=str(error)))
            return
        failed = {error.source for error in self._errors if error.is_resolve}
        if not entries:
            empty = make_label(tr("chats.lib.empty"), "muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list.addWidget(empty)
        for entry in entries:
            self._list.addWidget(_EntryRow(self, entry, resolve_error_key(entry) in failed))
        self._list.addStretch(1)

    def toggle(self, entry: ChatEntry, enabled: bool) -> None:
        try:
            set_enabled(self.gui.service.library_file, entry.key, enabled)
        except LibraryError as error:
            self._show_problem(tr("chats.lib.error_toggle", detail=str(error)))
            self.reload()
            return
        self._problem.hide()

    def _on_add(self) -> None:
        ref = self._ref.text()
        name = self._name.text() or None
        try:
            add_entry(self.gui.service.library_file, ref, name)
        except LibraryError as error:
            self._show_problem(tr("chats.lib.error_add", detail=str(error)))
            return
        self._ref.clear()
        self._name.clear()
        self._problem.hide()
        self._show_message("success", tr("chats.lib.added"))
        self.reload()

    def _show_problem(self, text: str) -> None:
        self._show_message("danger", text)

    def _show_message(self, tone: Tone, text: str) -> None:
        self._problem.set_tone(tone)
        self._problem.set_body(text)
        self._problem.show()
