"""The Data folder card: where the archive is, cloud-sync warning, and changing the folder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout

from chatimport.gui.i18n import tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.pages.data_common import toolbar
from chatimport.gui.pages.data_folder_dialog import FolderDialog
from chatimport.gui.pages.data_section import Section
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.labels import ElidedLabel, make_label
from chatimport.paths import is_cloud_synced

if TYPE_CHECKING:
    from concurrent.futures import Future

    from PySide6.QtWidgets import QWidget

    from chatimport.commands import CommandResult
    from chatimport.gui.pages.data_common import DataEnv

_ = _data_strings


class FolderCard(Section):
    def __init__(self, env: DataEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, "folder", "folder", parent=parent)
        kit = self.kit
        self._busy = False
        self._caption = make_label("", "caption")
        self.path_label = ElidedLabel("", "mono")
        self.path_label.setObjectName("DataFolderPath")
        self.copy_button = IconButton(kit, "copy", "", variant="secondary")
        self.open_button = IconButton(kit, "folder-open", "", variant="secondary")
        self.change_button = Button(kit, "", icon_name="sliders")
        self.missing = make_label("", "muted")
        self.cloud = Callout(kit, "warning", "")
        self._path_box = QFrame()
        set_role(self._path_box, "surface-sunken")
        self._path_row = QHBoxLayout(self._path_box)
        self._path_row.setSpacing(kit.px(SPACE[3]))
        self._path_row.addWidget(self.path_label, 1)
        self._path_row.addWidget(self.copy_button)
        self._path_row.addWidget(self.open_button)
        row = toolbar(kit)
        row.addWidget(self._path_box, 1)
        row.addWidget(self.change_button)
        self.content.addWidget(self._caption)
        self.content.addLayout(row)
        self.content.addWidget(self.missing)
        self.content.addWidget(self.cloud)
        self.copy_button.clicked.connect(self._copy)
        self.open_button.clicked.connect(lambda: env.open_folder(env.root))
        self.change_button.clicked.connect(self.change)
        env.root_changed.connect(self._render)
        bind_kit(kit, zoom=self._apply_sizes)
        self._apply_sizes()
        self.retranslate()

    def _apply_sizes(self) -> None:
        px = self.kit.px
        pad = px(SPACE[4])
        self._path_row.setContentsMargins(pad, px(SPACE[2]), px(SPACE[2]), px(SPACE[2]))

    def retranslate(self) -> None:
        self._caption.setText(tr("data.folder.current"))
        self.copy_button.set_tooltip(tr("data.folder.copy"))
        self.open_button.set_tooltip(tr("data.folder.open"))
        self._set_busy(self._busy)
        self.cloud.set_body(tr("data.folder.cloud"))
        self.missing.setText(tr("data.folder.missing"))
        self._render()

    def _render(self) -> None:
        root = self.env.root
        self.path_label.setText(str(root))
        self.path_label.setToolTip(str(root))
        self.missing.setVisible(not root.is_dir())
        self.cloud.setVisible(is_cloud_synced(root))

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(str(self.env.root))
        self.env.toast("info", tr("data.folder.copied"))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.set_busy(busy)
        self.change_button.setEnabled(not busy)
        self.change_button.setText(tr("data.folder.working" if busy else "data.folder.change"))

    def change(self) -> None:
        if self._busy:
            return
        dialog = FolderDialog(self.env.gui, self.env.root, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.chosen_path is None:
            return
        target, move = dialog.chosen_path, dialog.move_data
        key = "data.folder.confirm.move" if move else "data.folder.confirm.fresh"
        text = tr(key, old=str(self.env.root), new=str(target))
        if not self.env.confirm(
            tr("data.folder.confirm.title"), text, tr("data.folder.confirm.yes"), danger=False
        ):
            return
        self._set_busy(True)
        future = self.env.gui.bridge.execute("set_root", {"path": str(target), "move": move})
        self.env.runner.watch(future, self._changed)

    def _changed(self, done: Future[CommandResult]) -> None:
        self._set_busy(False)
        try:
            result = done.result()
        except Exception:
            self.env.unavailable()
            return
        if not result.ok:
            self.env.toast("danger", tr("data.folder.toast.failed"))
            return
        raw = result.data.get("path")
        new_root = Path(raw) if isinstance(raw, str) else self.env.root
        self.env.set_root(new_root)
        self.env.toast("success", tr("data.folder.toast.ok", path=str(new_root)))
