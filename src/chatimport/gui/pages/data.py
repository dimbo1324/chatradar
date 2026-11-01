"""The Data page: storage, clean-up, integrity, the data folder and export, in one column."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.pages.data_cleanup import CleanupCard
from chatimport.gui.pages.data_common import DataEnv
from chatimport.gui.pages.data_export import ExportCard
from chatimport.gui.pages.data_folder import FolderCard
from chatimport.gui.pages.data_integrity import IntegrityCard
from chatimport.gui.pages.data_storage import StorageCard
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.usage import ArchiveUsage, archive_usage

if TYPE_CHECKING:
    from concurrent.futures import Future

    from PySide6.QtGui import QShowEvent

    from chatimport.gui.context import GuiContext

_ = _data_strings


class DataPage(QWidget):
    title_key = "nav.data"
    subtitle_key = "data.subtitle"

    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        self._computed = False
        self._calculating = False
        self._again = False
        self.env = DataEnv(gui, self)
        self.storage = StorageCard(self.env)
        self.cleanup = CleanupCard(self.env)
        self.integrity = IntegrityCard(self.env)
        self.folder = FolderCard(self.env)
        self.export = ExportCard(self.env)

        content = QWidget()
        content.setObjectName("DataContent")
        self._content = content
        self._stack = QVBoxLayout(content)
        for card in (self.storage, self.cleanup, self.integrity, self.folder, self.export):
            self._stack.addWidget(card)
        self._stack.addStretch(1)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        wrap.addWidget(content, 100)
        wrap.addStretch(1)
        host = QWidget()
        host.setLayout(wrap)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(host)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        self.env.request_usage.connect(self.calculate)
        bind_kit(gui.kit, zoom=self._restyle)
        self._restyle()

    def calculate(self) -> None:
        """Compute the sizes on a worker thread; a request during a run repeats it once."""
        if self._calculating:
            self._again = True
            return
        self._calculating = True
        self._computed = True
        self.storage.set_busy(True)
        root = self.env.root
        self.env.runner.submit(lambda: archive_usage(root), self._calculated)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._computed:
            self.calculate()

    def _calculated(self, done: Future[ArchiveUsage]) -> None:
        self._calculating = False
        self.storage.set_busy(False)
        if done.exception() is None:
            self.env.set_usage(done.result())
        else:
            self.env.toast("danger", tr("data.storage.failed"))
        if self._again:
            self._again = False
            self.calculate()

    def _restyle(self) -> None:
        px = self.gui.kit.px
        self._content.setMaximumWidth(px(LAYOUT["content_max"]))
        pad = px(SPACE[8])
        self._stack.setContentsMargins(pad, px(SPACE[7]), pad, px(SPACE[8]))
        self._stack.setSpacing(px(SPACE[6]))
