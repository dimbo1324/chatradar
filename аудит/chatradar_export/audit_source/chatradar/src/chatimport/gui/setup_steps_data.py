"""Wizard steps three and four: the chats to archive and the archive folder."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from chatimport.config import ConfigError
from chatimport.config_edit import set_output_root
from chatimport.gui.i18n import plural, tr
from chatimport.gui.pages.support import clear_layout
from chatimport.gui.setup_logic import (
    FolderCheck,
    RefResult,
    add_refs,
    check_folder,
    current_root,
    read_state,
    split_refs,
)
from chatimport.gui.setup_steps import WizardEnv, WizardStep
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import ElidedLabel, make_label

if TYPE_CHECKING:
    from chatimport.gui.widgets.base import Tone

log = logging.getLogger(__name__)

INPUT_ROWS: Final = 5
RESULT_TONES: Final[dict[str, Tone]] = {
    "added": "success",
    "duplicate": "muted",
    "invalid": "danger",
    "error": "danger",
}
RESULT_ICONS: Final = {
    "added": "check-circle",
    "duplicate": "info",
    "invalid": "x-circle",
    "error": "x-circle",
}


class ChatsStep(WizardStep):
    name = "chats"
    skippable = True

    def __init__(self, env: WizardEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, parent)
        self._count = 0
        self._known = make_label("", "caption")
        self._input = QPlainTextEdit()
        self._input.setFixedHeight(self.kit.px(INPUT_ROWS * 24))
        self._add = Button(self.kit, variant="primary", icon_name="plus")
        self._add.clicked.connect(self._on_add)
        self._empty = make_label("", "error", wrap=True)
        self._empty.hide()
        self._results = QVBoxLayout()
        self._results.setSpacing(self.kit.px(SPACE[2]))
        row = QHBoxLayout()
        row.addWidget(self._add)
        row.addStretch(1)
        self.column.addWidget(self._known)
        self.column.addWidget(self._input)
        self.column.addLayout(row)
        self.column.addWidget(self._empty)
        self.column.addLayout(self._results)
        self.column.addStretch(1)
        self._last: list[RefResult] = []
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self._input.setPlaceholderText(tr("setup.chats.placeholder"))
        self._input.setAccessibleName(tr("setup.chats.heading"))
        self._add.setText(tr("setup.chats.add"))
        self._empty.setText(tr("setup.chats.empty"))
        self._render_count()
        self._render_results()

    def enter(self) -> None:
        context = self.env.context
        state = read_state(
            context.paths.config_file, context.paths.session_file, context.library_file
        )
        self._count = state.chats
        self._render_count()
        self.changed.emit()

    def can_advance(self) -> bool:
        return self._count > 0

    def _render_count(self) -> None:
        self._known.setText(plural(self._count, "setup.chats.known") if self._count else "")
        self._known.setVisible(self._count > 0)

    def _on_add(self) -> None:
        text = self._input.toPlainText()
        refs = split_refs(text)
        self._empty.setVisible(not refs)
        if not refs:
            return
        self._last = add_refs(self.env.context.library_file, text)
        leftover = [
            ref
            for ref, result in zip(refs, self._last, strict=True)
            if result.status in ("invalid", "error")
        ]
        self._input.setPlainText("\n".join(leftover))
        self._render_results()
        self.enter()

    def _render_results(self) -> None:
        clear_layout(self._results)
        for result in self._last:
            tone = RESULT_TONES[result.status]
            chip = Chip(
                self.kit,
                tr(f"setup.chats.result.{result.status}"),
                tone,
                icon_name=RESULT_ICONS[result.status],
            )
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(self.kit.px(SPACE[4]))
            line.addWidget(chip)
            label = ElidedLabel(result.ref, "mono")
            if result.detail:
                label.setToolTip(result.detail)
            line.addWidget(label, 1)
            self._results.addWidget(row)


class FolderStep(WizardStep):
    name = "folder"

    def __init__(self, env: WizardEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, parent)
        self._check = FolderCheck(None)
        self._path_label = make_label("", "caption")
        self._path = QLineEdit()
        self._path.setProperty("role", "mono")
        self._browse = Button(self.kit, icon_name="folder-open")
        self._browse.clicked.connect(self._on_browse)
        self._path.editingFinished.connect(self._validate)
        self._verdict = Callout(self.kit, "info", "")
        self._verdict.hide()
        self._cloud = Callout(self.kit, "warning", "")
        self._cloud.hide()
        self._problem = Callout(self.kit, "danger", "")
        self._problem.hide()
        field = QHBoxLayout()
        field.setSpacing(self.kit.px(SPACE[3]))
        field.addWidget(self._path, 1)
        field.addWidget(self._browse)
        self.column.addWidget(self._path_label)
        self.column.addLayout(field)
        self.column.addWidget(self._verdict)
        self.column.addWidget(self._cloud)
        self.column.addWidget(self._problem)
        self.column.addStretch(1)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self._path_label.setText(tr("setup.folder.path"))
        self._path.setAccessibleName(tr("setup.folder.path"))
        self._browse.setText(tr("setup.folder.browse"))
        self._cloud.set_body(tr("setup.folder.cloud"))
        if self._path.text().strip():
            self._validate()

    def enter(self) -> None:
        if not self._path.text().strip():
            self._path.setText(str(current_root(self.env.context.paths.config_file)))
        self._validate()

    def can_advance(self) -> bool:
        return self._check.path is not None

    def _current(self) -> FolderCheck:
        context = self.env.context
        return check_folder(
            self._path.text(), current_root(context.paths.config_file), context.paths.base
        )

    def _validate(self) -> bool:
        self._problem.hide()
        check = self._current()
        self._check = check
        if check.path is None:
            self._verdict.set_tone("danger")
            self._verdict.set_body(tr("setup.folder.invalid", detail=check.error))
        else:
            self._verdict.set_tone("success")
            self._verdict.set_body(tr("setup.folder.valid", path=str(check.path)))
        self._verdict.show()
        self._cloud.setVisible(check.cloud)
        self.changed.emit()
        return check.path is not None

    def _on_browse(self) -> None:
        start = self._path.text().strip() or str(current_root(self.env.context.paths.config_file))
        picked = QFileDialog.getExistingDirectory(self, tr("setup.folder.pick"), start)
        if picked:
            self._path.setText(picked)
            self._validate()

    def commit(self) -> bool:
        if not self._validate():
            return False
        check = self._check
        if check.changed and check.path is not None:
            try:
                set_output_root(self.env.context.paths.config_file, check.path)
            except ConfigError, OSError:
                log.exception("the data folder could not be saved")
                self._problem.set_body(tr("setup.folder.error.write"))
                self._problem.show()
                return False
        return True
