"""The Cleanup card: preview what removing the oldest 25/50/75 % would do, then do it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QHeaderView, QTableView

from chatimport.gui.format import format_bytes
from chatimport.gui.i18n import plural, tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.models.data_models import PreviewColumn, PreviewModel
from chatimport.gui.pages.data_common import (
    ChatSelector,
    FieldRow,
    fit_table,
    prepare_table,
    toolbar,
)
from chatimport.gui.pages.data_section import Section
from chatimport.gui.strings import current_language
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.labels import make_label
from chatimport.gui.widgets.segmented import Segmented, SegmentOption
from chatimport.gui.widgets.table import configure_table
from chatimport.trim import ALLOWED_PERCENTS, TrimPreview, preview_percent

if TYPE_CHECKING:
    from concurrent.futures import Future

    from PySide6.QtWidgets import QWidget

    from chatimport.commands import CommandResult
    from chatimport.gui.pages.data_common import DataEnv

_ = _data_strings


class CleanupCard(Section):
    def __init__(self, env: DataEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, "cleanup", "trash", parent=parent)
        kit = self.kit
        self._preview: TrimPreview | None = None
        self._busy = False
        self.chat = ChatSelector(allow_all=True)
        self.share = Segmented(kit, self._options(), str(ALLOWED_PERCENTS[1]), compact=True)
        self.preview_button = Button(kit, "", icon_name="search")
        self.run_button = Button(kit, "", variant="danger", icon_name="trash")
        self.run_button.setEnabled(False)
        self._chat_field = FieldRow(kit, "", self.chat)
        self._share_field = FieldRow(kit, "", self.share)
        row = toolbar(kit)
        row.addWidget(self._chat_field, 1)
        row.addWidget(self._share_field)
        actions = toolbar(kit)
        actions.addStretch(1)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.run_button)
        self.hint = make_label("", "muted", wrap=True)
        self.summary = make_label("", None, wrap=True)
        self.note = Callout(kit, "info", "")
        self.model = PreviewModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        configure_table(self.table, kit)
        prepare_table(self.table)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(PreviewColumn.CHAT, QHeaderView.ResizeMode.Stretch)
        for number in (PreviewColumn.RECORDS, PreviewColumn.SIZE, PreviewColumn.OLDEST):
            header.setSectionResizeMode(number, QHeaderView.ResizeMode.ResizeToContents)
        self.table.hide()
        self.content.addLayout(row)
        self.content.addLayout(actions)
        self.content.addWidget(self.summary)
        self.content.addWidget(self.hint)
        self.content.addWidget(self.table)
        self.content.addWidget(self.note)
        self.chat.currentIndexChanged.connect(self._invalidate)
        self.share.selected.connect(self._invalidate)
        self.preview_button.clicked.connect(self.preview)
        self.run_button.clicked.connect(self.run)
        env.usage_changed.connect(lambda: self.chat.set_chats(env.chats()))
        bind_kit(kit, zoom=self._apply_sizes)
        self._apply_sizes()
        self.retranslate()

    def _options(self) -> list[SegmentOption]:
        return [SegmentOption(str(pct), f"{pct}%") for pct in ALLOWED_PERCENTS]

    def selected_pct(self) -> int:
        return int(self.share.value)

    def retranslate(self) -> None:
        self._chat_field.set_caption(tr("data.cleanup.chat"))
        self._share_field.set_caption(tr("data.cleanup.share"))
        self.preview_button.setText(tr("data.cleanup.preview"))
        self.run_button.setText(tr("data.cleanup.run"))
        self.hint.setText(tr("data.cleanup.hint"))
        self.note.set_body(tr("data.cleanup.size_note"))
        self.chat.rebuild()
        self.model.retranslate()
        self._render_summary()

    def _apply_sizes(self) -> None:
        fit_table(self.table, self.kit, self.model.rowCount())

    def _invalidate(self, *_args: object) -> None:
        if self._preview is None:
            return
        self._preview = None
        self.model.set_preview(())
        self.run_button.setEnabled(False)
        self._show_table(False)
        self._render_summary()

    def _show_table(self, shown: bool) -> None:
        self.table.setVisible(shown)
        self.hint.setVisible(not shown)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.set_busy(busy)
        self.preview_button.setEnabled(not busy)
        self.run_button.setEnabled(not busy and self._can_run())

    def _can_run(self) -> bool:
        return self._preview is not None and self._preview.records_deleted > 0

    def preview(self) -> None:
        if self._busy:
            return
        root, pct, chat_id = self.env.root, self.selected_pct(), self.chat.chat_id()
        self._set_busy(True)
        self.env.runner.submit(lambda: preview_percent(root, pct, chat_id), self._previewed)

    def _previewed(self, done: Future[TrimPreview]) -> None:
        self._set_busy(False)
        if done.exception() is not None:
            self.env.toast("danger", tr("data.failed"))
            return
        self._preview = done.result()
        self.model.set_preview(self._preview.chats)
        self._show_table(True)
        fit_table(self.table, self.kit, self.model.rowCount())
        self.run_button.setEnabled(self._can_run())
        self._render_summary()

    def _render_summary(self) -> None:
        preview = self._preview
        self.summary.setVisible(preview is not None)
        if preview is None:
            return
        if preview.records_deleted == 0:
            self.summary.setText(tr("data.cleanup.summary_none"))
            return
        size = format_bytes(preview.bytes_freed, current_language())
        self.summary.setText(plural(preview.records_deleted, "data.cleanup.summary", size=size))

    def _scope(self) -> str:
        return (
            tr("data.cleanup.confirm.scope_all")
            if self.chat.chat_id() is None
            else (self.chat.title())
        )

    def run(self) -> None:
        preview = self._preview
        if self._busy or preview is None or preview.records_deleted == 0:
            return
        pct = preview.pct
        size = format_bytes(preview.bytes_freed, current_language())
        text = plural(
            preview.records_deleted, "data.cleanup.confirm.text", size=size, scope=self._scope()
        )
        if not self.env.confirm(
            tr("data.cleanup.confirm.title", pct=pct), text, tr("data.cleanup.confirm.yes")
        ):
            return
        args: dict[str, Any] = {"pct": pct}
        chat_id = self.chat.chat_id()
        if chat_id is not None:
            args["chat"] = chat_id
        self._set_busy(True)
        self.env.runner.watch(self.env.gui.bridge.execute("trim", args), self._trimmed)

    def _trimmed(self, done: Future[CommandResult]) -> None:
        self._set_busy(False)
        try:
            result = done.result()
        except Exception:
            self.env.unavailable()
            return
        if not result.ok:
            self.env.toast("danger", tr("data.cleanup.toast.failed"))
            return
        records = result.data.get("records")
        freed = result.data.get("bytes")
        count = records if isinstance(records, int) else 0
        size = format_bytes(freed if isinstance(freed, int) else 0, current_language())
        self.env.toast("success", plural(count, "data.cleanup.toast.ok", size=size))
        self._invalidate()
        self.env.request_usage.emit()
