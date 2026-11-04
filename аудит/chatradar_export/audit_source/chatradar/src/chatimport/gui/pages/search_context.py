"""The context drawer of the Search page: the messages around a result and the actions on it."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from chatimport.gui.format import format_exact
from chatimport.gui.i18n import tr
from chatimport.gui.models.search_spans import find_spans, highlight_html
from chatimport.gui.pages.support import clear_layout
from chatimport.gui.tokens import RADIUS, SPACE, TEXT
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.labels import ElidedLabel, make_label

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from chatimport.gui.kit import UiKit
    from chatimport.gui.pages.search_worker import SearchWorker
    from chatimport.gui.pages.support import MainThreadRunner
    from chatimport.search_types import ContextMessage, SearchHit

log = logging.getLogger(__name__)

CONTEXT_BEFORE: Final = 3
CONTEXT_AFTER: Final = 3


class ContextPanel(QFrame):
    close_requested = Signal()
    open_requested = Signal()
    copy_link_requested = Signal()
    copy_text_requested = Signal()

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("ContextPanel")
        self._hit: SearchHit | None = None
        self._rows: list[tuple[QFrame, bool]] = []
        self._title = make_label("", "title")
        self._subtitle = ElidedLabel("")
        self.close_button = IconButton(kit, "x", "")
        head = QHBoxLayout()
        head.addWidget(self._title, 1)
        head.addWidget(self.close_button)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._note = make_label("", "muted", wrap=True)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._note)
        column.addLayout(self._rows_layout)
        column.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(holder)
        self._holder = holder

        self.open_button = Button(kit, "", variant="primary", size="sm", icon_name="external")
        self.link_button = Button(kit, "", size="sm", icon_name="copy")
        self.text_button = Button(kit, "", size="sm", icon_name="copy")
        actions = QHBoxLayout()
        for button in (self.open_button, self.link_button, self.text_button):
            actions.addWidget(button)
        actions.addStretch(1)

        self._column = QVBoxLayout(self)
        self._column.addLayout(head)
        self._column.addWidget(self._subtitle)
        self._column.addWidget(self._scroll, 1)
        self._column.addLayout(actions)

        self.close_button.clicked.connect(self.close_requested)
        self.open_button.clicked.connect(self.open_requested)
        self.link_button.clicked.connect(self.copy_link_requested)
        self.text_button.clicked.connect(self.copy_text_requested)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()
        self._sync_buttons()

    @property
    def hit(self) -> SearchHit | None:
        return self._hit

    @property
    def message_count(self) -> int:
        return len(self._rows)

    @property
    def note(self) -> str:
        return self._note.text()

    def show_loading(self, hit: SearchHit) -> None:
        self._begin(hit)
        self._note.setText(tr("find.ctx.loading"))

    def show_messages(
        self, hit: SearchHit, messages: tuple[ContextMessage, ...], needle: str
    ) -> None:
        self._begin(hit)
        if not messages:
            self._note.setText(tr("find.ctx.missing"))
            return
        self._note.setText("")
        for message in messages:
            self._add_row(message, needle)
        self._restyle()

    def _begin(self, hit: SearchHit) -> None:
        self._hit = hit
        clear_layout(self._rows_layout)
        self._rows.clear()
        self._subtitle.setText(hit.chat_title)
        self._subtitle.setToolTip(hit.chat_title)
        self._sync_buttons()

    def _add_row(self, message: ContextMessage, needle: str) -> None:
        row = QFrame()
        row.setObjectName("ContextRow")
        meta = f"{format_exact(message.date)}"
        if message.edited:
            meta = f"{meta} · {tr('find.edited')}"
        if message.is_target:
            meta = f"{tr('find.ctx.target')} · {meta}"
        head = QLabel(meta)
        body = QLabel()
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        spans = find_spans(message.text, needle) if message.is_target else []
        body.setText(highlight_html(message.text, spans, self._tint()))
        layout = QVBoxLayout(row)
        layout.addWidget(head)
        layout.addWidget(body)
        row.setProperty("target", message.is_target)
        self._rows_layout.addWidget(row)
        self._rows.append((row, message.is_target))

    def _tint(self) -> str:
        return self.kit.palette.accent_soft_border

    def _sync_buttons(self) -> None:
        hit = self._hit
        self.open_button.setEnabled(hit is not None and hit.link is not None)
        self.link_button.setEnabled(hit is not None and hit.link is not None)
        self.text_button.setEnabled(hit is not None)
        self.open_button.setToolTip(
            "" if self.open_button.isEnabled() else tr("find.ctx.open_none")
        )

    def _retranslate(self) -> None:
        self._title.setText(tr("find.ctx.title"))
        self.close_button.set_tooltip(tr("find.ctx.close"))
        self.open_button.setText(tr("find.ctx.open"))
        self.link_button.setText(tr("find.ctx.copy_link"))
        self.text_button.setText(tr("find.ctx.copy_text"))
        self.setAccessibleName(tr("find.ctx.title"))
        self._sync_buttons()

    def _restyle(self) -> None:
        palette = self.kit.palette
        px = self.kit.px
        self._column.setContentsMargins(px(SPACE[5]), px(SPACE[5]), px(SPACE[5]), px(SPACE[5]))
        self._column.setSpacing(px(SPACE[4]))
        self._rows_layout.setSpacing(px(SPACE[3]))
        self.setStyleSheet(
            f"#ContextPanel {{ background: {palette.surface};"
            f" border-left: 1px solid {palette.border}; }}"
        )
        self._holder.setStyleSheet(f"background: {palette.surface};")
        for row, target in self._rows:
            fill = palette.accent_soft if target else palette.surface_sunken
            edge = palette.accent if target else palette.border
            row.setStyleSheet(
                f"#ContextRow {{ background: {fill}; border: 1px solid {edge};"
                f" border-radius: {px(RADIUS['md'])}px; }}"
                f"#ContextRow QLabel {{ background: transparent; color: {palette.fg};"
                f" font-size: {px(TEXT['base'])}px; }}"
            )
            labels = row.findChildren(QLabel)
            if labels:
                labels[0].setStyleSheet(
                    f"color: {palette.fg_muted}; font-size: {px(TEXT['xs'])}px;"
                    " background: transparent;"
                )
            layout = row.layout()
            if layout is not None:
                layout.setContentsMargins(px(SPACE[4]), px(SPACE[3]), px(SPACE[4]), px(SPACE[3]))
                layout.setSpacing(px(SPACE[2]))
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")


class ContextController:
    """Opens, reloads and closes the drawer; answers for a hit no longer shown are dropped."""

    def __init__(
        self,
        panel: ContextPanel,
        worker: SearchWorker,
        runner: MainThreadRunner,
        needle: Callable[[], str],
    ) -> None:
        self._panel = panel
        self._worker = worker
        self._runner = runner
        self._needle = needle
        self._seq = 0
        self.is_open = False

    def open(self, hit: SearchHit) -> bool:
        """Show the drawer for `hit`; False when it already shows exactly this hit."""
        if self.is_open and self._panel.hit == hit:
            return False
        self.is_open = True
        self._panel.show()
        self.load(hit)
        return True

    def load(self, hit: SearchHit) -> None:
        self._seq += 1
        seq = self._seq
        self._panel.show_loading(hit)
        chat_id, msg_id = hit.chat_id, hit.msg_id
        future = self._worker.run(
            lambda backend: (
                ()
                if backend is None
                else backend.context(chat_id, msg_id, CONTEXT_BEFORE, CONTEXT_AFTER)
            )
        )
        self._runner.watch(future, lambda done: self._arrived(seq, hit, done))

    def _arrived(self, seq: int, hit: SearchHit, done: Future[tuple[ContextMessage, ...]]) -> None:
        if seq != self._seq:
            return
        try:
            messages = done.result()
        except Exception as error:
            log.warning("loading the context failed: %s", type(error).__name__)
            messages = ()
        self._panel.show_messages(hit, messages, self._needle())

    def close(self) -> None:
        self.is_open = False
        self._seq += 1
        self._panel.hide()

    def target(self) -> SearchHit | None:
        return self._panel.hit if self.is_open else None
