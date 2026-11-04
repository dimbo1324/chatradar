"""The "Change folder" dialog: pick a folder, see at once whether it can be used."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout

from chatimport.gui.i18n import tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.pages.data_common import breakable
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.labels import make_label
from chatimport.paths import is_cloud_synced, normalize_root
from chatimport.ports import ChatImportError
from chatimport.setroot import validate_new_root

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QWidget

    from chatimport.gui.context import GuiContext

_ = _data_strings
DIALOG_WIDTH: Final = 560


class FolderDialog(QDialog):
    """`chosen_path` and `move` are valid after `exec()` returned Accepted.

    Validation (`setroot.validate_new_root`) runs when the path is committed, not per keystroke:
    it creates the folder and writes a probe file there, as `set-root` itself does.
    """

    def __init__(self, gui: GuiContext, current: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        self._current = current
        self.chosen_path: Path | None = None
        kit = gui.kit
        self.setMinimumWidth(kit.px(DIALOG_WIDTH))
        self._lede = make_label("", "muted", wrap=True)
        self._path_label = make_label("", "caption")
        self.path = QLineEdit()
        self.path.setProperty("role", "mono")
        self.browse = Button(kit, "", icon_name="folder-open")
        self.move_box = QCheckBox()
        self.move_box.setChecked(True)
        self._move_hint = make_label("", "muted", wrap=True)
        self.verdict = Callout(kit, "info", "")
        self.verdict.hide()
        self.apply = Button(kit, "", variant="primary")
        self.apply.setEnabled(False)
        self.cancel = Button(kit, "")
        field = QHBoxLayout()
        field.setSpacing(kit.px(SPACE[3]))
        field.addWidget(self.path, 1)
        field.addWidget(self.browse)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.setSpacing(kit.px(SPACE[3]))
        footer.addWidget(self.cancel)
        footer.addWidget(self.apply)
        layout = QVBoxLayout(self)
        gap = kit.px(SPACE[5])
        layout.setContentsMargins(gap, gap, gap, gap)
        layout.setSpacing(gap)
        layout.addWidget(self._lede)
        layout.addWidget(self._path_label)
        layout.addLayout(field)
        layout.addWidget(self.move_box)
        layout.addWidget(self._move_hint)
        layout.addWidget(self.verdict)
        layout.addLayout(footer)
        self.browse.clicked.connect(self._browse)
        self.path.editingFinished.connect(self.validate)
        self.move_box.toggled.connect(self._on_move_toggled)
        self.apply.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        bind_kit(kit, language=self._retranslate)
        self._retranslate()

    @property
    def move_data(self) -> bool:
        return self.move_box.isChecked()

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("data.folder.dialog.title"))
        self._lede.setText(tr("data.folder.dialog.lede"))
        self._path_label.setText(tr("data.folder.dialog.path"))
        self.path.setAccessibleName(tr("data.folder.dialog.path"))
        self.browse.setText(tr("data.folder.dialog.browse"))
        self.move_box.setText(tr("data.folder.dialog.move"))
        self._move_hint.setText(tr("data.folder.dialog.move_hint"))
        self.apply.setText(tr("data.folder.dialog.apply"))
        self.cancel.setText(tr("common.cancel"))
        if self.path.text().strip():
            self.validate()

    def _on_move_toggled(self, _checked: bool) -> None:
        self.validate()

    def _browse(self) -> None:
        start = self.path.text().strip() or str(self._current.parent)
        picked = QFileDialog.getExistingDirectory(self, tr("data.folder.dialog.pick"), start)
        if picked:
            self.path.setText(picked)
            self.validate()

    def validate(self) -> bool:
        text = self.path.text().strip()
        self.chosen_path = None
        self.apply.setEnabled(False)
        if not text:
            self.verdict.hide()
            return False
        target = normalize_root(text)
        try:
            validate_new_root(
                target,
                self._current,
                app_base=self.gui.service.paths.base,
                move=self.move_data,
            )
        except (ChatImportError, OSError) as error:
            self.verdict.set_tone("danger")
            self.verdict.set_body(tr("data.folder.dialog.invalid", detail=str(error)))
            self.verdict.show()
            return False
        self.chosen_path = target
        cloud = is_cloud_synced(target)
        self.verdict.set_tone("warning" if cloud else "success")
        lines = [tr("data.folder.dialog.valid", path=breakable(str(target)))]
        if cloud:
            lines.append(tr("data.folder.cloud"))
        self.verdict.set_body("\n".join(lines))
        self.verdict.show()
        self.apply.setEnabled(True)
        return True
