"""The Integrity card: run the `check` command, list what it found, repair on request."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QHeaderView, QTableView

from chatimport.gui.i18n import plural, tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.models.data_models import IssueColumn, IssueRow, IssuesModel, parse_issues
from chatimport.gui.pages.data_common import SeverityDelegate, fit_table, prepare_table, toolbar
from chatimport.gui.pages.data_section import Section
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import make_label
from chatimport.gui.widgets.table import configure_table
from chatimport.integrity import ERROR, INFO, WARNING

if TYPE_CHECKING:
    from concurrent.futures import Future

    from PySide6.QtWidgets import QWidget

    from chatimport.commands import CommandResult
    from chatimport.gui.pages.data_common import DataEnv
    from chatimport.gui.widgets.base import Tone

_ = _data_strings
SEVERITY_COUNTS: tuple[tuple[str, Tone], ...] = (
    (ERROR, "danger"),
    (WARNING, "warning"),
    (INFO, "info"),
)
SEVERITY_WIDTH = 120
FOLDER_WIDTH = 240


class IntegrityCard(Section):
    def __init__(self, env: DataEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, "integrity", "shield-check", parent=parent)
        kit = self.kit
        self._busy = False
        self._rows: list[IssueRow] | None = None
        self.run_button = Button(kit, "", variant="primary", icon_name="shield-check")
        self.repair_button = Button(kit, "", icon_name="refresh")
        self.repair_button.setEnabled(False)
        self.chips = {
            severity: Chip(kit, "", tone, icon_name=icon)
            for (severity, tone), icon in zip(
                SEVERITY_COUNTS, ("x-circle", "alert", "info"), strict=True
            )
        }
        row = toolbar(kit)
        row.addWidget(self.run_button)
        row.addWidget(self.repair_button)
        row.addSpacing(kit.px(SPACE[4]))
        for chip in self.chips.values():
            row.addWidget(chip)
            chip.hide()
        row.addStretch(1)
        self.hint = make_label("", "muted", wrap=True)
        self.ok = Callout(kit, "success", "")
        self.ok.hide()
        self.model = IssuesModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        configure_table(self.table, kit)
        prepare_table(self.table)
        self.delegate = SeverityDelegate(kit)
        self.table.setItemDelegate(self.delegate)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(IssueColumn.SEVERITY, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(IssueColumn.FOLDER, QHeaderView.ResizeMode.Fixed)
        self.table.hide()
        self.content.addLayout(row)
        self.content.addWidget(self.hint)
        self.content.addWidget(self.table)
        self.content.addWidget(self.ok)
        self.run_button.clicked.connect(self.run_check)
        self.repair_button.clicked.connect(self.repair)
        bind_kit(kit, zoom=self._apply_sizes)
        self._apply_sizes()
        self.retranslate()

    def retranslate(self) -> None:
        self._sync_buttons()
        self.hint.setText(tr("data.integrity.hint"))
        self.ok.set_title(tr("data.integrity.ok_title"))
        self.ok.set_body(tr("data.integrity.ok_text"))
        self.model.retranslate()
        self._render()

    def _apply_sizes(self) -> None:
        header = self.table.horizontalHeader()
        header.resizeSection(IssueColumn.SEVERITY, self.kit.px(SEVERITY_WIDTH))
        header.resizeSection(IssueColumn.FOLDER, self.kit.px(FOLDER_WIDTH))
        fit_table(self.table, self.kit, self.model.rowCount())

    def _sync_buttons(self) -> None:
        self.run_button.setText(
            tr("data.integrity.running" if self._busy else "data.integrity.run")
        )
        self.run_button.setEnabled(not self._busy)
        has_issues = bool(self._rows)
        self.repair_button.setText(tr("data.integrity.repair"))
        self.repair_button.setEnabled(has_issues and not self._busy)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.set_busy(busy)
        self._sync_buttons()

    def run_check(self) -> None:
        self._send(repair=False)

    def repair(self) -> None:
        if not self._rows or self._busy:
            return
        if self.env.confirm(
            tr("data.integrity.repair.title"),
            tr("data.integrity.repair.text"),
            tr("data.integrity.repair.yes"),
            danger=False,
        ):
            self._send(repair=True)

    def _send(self, *, repair: bool) -> None:
        if self._busy:
            return
        self._set_busy(True)
        future = self.env.gui.bridge.execute("check", {"repair": repair})
        self.env.runner.watch(future, lambda done: self._checked(done, repair=repair))

    def _checked(self, done: Future[CommandResult], *, repair: bool) -> None:
        self._set_busy(False)
        try:
            result = done.result()
        except Exception:
            self.env.unavailable()
            return
        if not result.ok:
            self.env.toast("danger", tr("data.integrity.toast.failed"))
            return
        self._rows = parse_issues(result.data)
        self.model.set_issues(self._rows)
        self._sync_buttons()
        self._render()
        if repair:
            self.env.toast("success", tr("data.integrity.toast.repaired"))
            self.env.request_usage.emit()

    def _render(self) -> None:
        rows = self._rows
        for severity, chip in self.chips.items():
            count = sum(1 for row in rows or () if row.severity == severity)
            chip.setVisible(count > 0)
            chip.set_text(plural(count, f"data.integrity.count.{severity}"))
        self.hint.setVisible(rows is None)
        self.table.setVisible(bool(rows))
        self.ok.setVisible(rows is not None and not rows)
        fit_table(self.table, self.kit, self.model.rowCount())
