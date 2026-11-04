"""The Export card: one chat as a JSON file, names left out unless asked."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout

from chatimport.export import EXPORTS_DIR, export_chat_json
from chatimport.gui.i18n import tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.pages.data_common import ChatSelector, FieldRow, breakable, toolbar
from chatimport.gui.pages.data_section import Section
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.labels import ElidedLabel, make_label
from chatimport.gui.widgets.switch import SwitchRow
from chatimport.storage.layout import find_chat_folder

if TYPE_CHECKING:
    from concurrent.futures import Future

    from PySide6.QtWidgets import QWidget

    from chatimport.gui.pages.data_common import DataEnv

_ = _data_strings


class ExportCard(Section):
    def __init__(self, env: DataEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, "export", "upload", parent=parent)
        kit = self.kit
        self._busy = False
        self._destination: Path | None = None
        self._last: Path | None = None
        self.chat = ChatSelector(allow_all=False)
        self._chat_field = FieldRow(kit, "", self.chat)
        self.names = SwitchRow(kit, "", "", checked=False)
        self.names_warning = Callout(kit, "warning", "")
        self.names_warning.hide()
        self._dest_caption = make_label("", "caption")
        self.dest_label = ElidedLabel("", "mono")
        self.browse = Button(kit, "", icon_name="folder-open")
        self.reset = Button(kit, "", variant="ghost", icon_name="x")
        self._dest_box = QFrame()
        set_role(self._dest_box, "surface-sunken")
        self._dest_row = QHBoxLayout(self._dest_box)
        self._dest_row.addWidget(self.dest_label, 1)
        self._dest_hint = make_label("", "muted")
        self.run_button = Button(kit, "", variant="primary", icon_name="upload")
        self.open_button = Button(kit, "", size="sm", icon_name="folder-open")
        self.done_row = Callout(kit, "success", "", action=self.open_button)
        self.done_row.hide()
        self.empty = make_label("", "muted")
        dest = toolbar(kit)
        dest.addWidget(self._dest_box, 1)
        dest.addWidget(self.browse)
        dest.addWidget(self.reset)
        head = toolbar(kit)
        head.addWidget(self._chat_field, 1)
        head.addStretch(1)
        head.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.content.addLayout(head)
        self.content.addWidget(self.names)
        self.content.addWidget(self.names_warning)
        self.content.addWidget(self._dest_caption)
        self.content.addLayout(dest)
        self.content.addWidget(self._dest_hint)
        self.content.addWidget(self.empty)
        self.content.addWidget(self.done_row)
        self.names.toggled.connect(self.names_warning.setVisible)
        self.browse.clicked.connect(self._browse)
        self.reset.clicked.connect(self._reset)
        self.run_button.clicked.connect(self.export)
        self.open_button.clicked.connect(self._open)
        env.usage_changed.connect(self._on_usage)
        env.root_changed.connect(self._render_destination)
        bind_kit(kit, zoom=self._apply_sizes)
        self._apply_sizes()
        self.retranslate()

    def _apply_sizes(self) -> None:
        px = self.kit.px
        self._dest_row.setContentsMargins(px(SPACE[4]), px(SPACE[2]), px(SPACE[4]), px(SPACE[2]))

    def retranslate(self) -> None:
        self._chat_field.set_caption(tr("data.export.chat"))
        self.names.set_texts(tr("data.export.names"), tr("data.export.names_hint"))
        self.names_warning.set_body(tr("data.export.names_warning"))
        self._dest_caption.setText(tr("data.export.destination"))
        self.browse.setText(tr("data.export.browse"))
        self.open_button.setText(tr("data.export.open"))
        self.empty.setText(tr("data.export.no_chat"))
        self._set_busy(self._busy)
        self.chat.rebuild()
        self._render_destination()
        if self._last is not None:
            self.done_row.set_body(tr("data.export.done", path=breakable(str(self._last))))

    def _on_usage(self) -> None:
        self.chat.set_chats(self.env.chats())
        self.empty.setVisible(self.chat.count() == 0)
        self.run_button.setEnabled(self.chat.count() > 0 and not self._busy)

    def _render_destination(self) -> None:
        shown = self._destination or self.env.root / EXPORTS_DIR
        self.dest_label.setText(str(shown))
        self.dest_label.setToolTip(str(shown))
        self._dest_hint.setVisible(self._destination is None)
        self._dest_hint.setText(tr("data.export.default_dest"))
        self.reset.setVisible(self._destination is not None)
        self.reset.setToolTip(tr("data.export.default_dest"))

    def _browse(self) -> None:
        start = str(self._destination or self.env.root)
        picked = QFileDialog.getExistingDirectory(self, tr("data.export.pick"), start)
        if picked:
            self._destination = Path(picked)
            self._render_destination()

    def _reset(self) -> None:
        self._destination = None
        self._render_destination()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.set_busy(busy)
        self.run_button.setText(tr("data.export.running" if busy else "data.export.run"))
        self.run_button.setEnabled(not busy and self.chat.count() > 0)

    def export(self) -> None:
        chat_id = self.chat.chat_id()
        if self._busy or chat_id is None:
            return
        root, names, destination = self.env.root, self.names.is_checked(), self._destination
        self.done_row.hide()
        self._set_busy(True)

        def work() -> Path | None:
            folder = find_chat_folder(root, chat_id)
            if folder is None:
                return None
            out = None if destination is None else destination / f"{folder.name}.json"
            return export_chat_json(folder, out, include_names=names)

        self.env.runner.submit(work, self._exported)

    def _exported(self, done: Future[Path | None]) -> None:
        self._set_busy(False)
        if done.exception() is not None:
            self.env.toast("danger", tr("data.export.toast.failed"))
            return
        path = done.result()
        if path is None:
            self.env.toast("warning", tr("data.export.toast.no_folder"))
            return
        self._last = path
        self.done_row.set_body(tr("data.export.done", path=breakable(str(path))))
        self.done_row.show()
        self.env.toast("success", tr("data.export.toast.ok", path=str(path)))

    def _open(self) -> None:
        if self._last is not None:
            self.env.open_folder(self._last.parent)
