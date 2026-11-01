"""What the owner can do with selected chats: commands to the service, folder and export.

Commands go through the bridge and come back as toasts built from translation keys; the text of
an exception never reaches the screen. Destructive ones (refetch, trim) ask first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QMenu, QMessageBox

from chatimport.export import export_chat_json
from chatimport.gui.i18n import plural, tr
from chatimport.gui.icons import icon
from chatimport.gui.locales import chats as _chat_strings
from chatimport.gui.pages.support import MainThreadRunner, notify
from chatimport.gui.tokens import LAYOUT
from chatimport.storage.layout import find_chat_folder

if TYPE_CHECKING:
    from collections.abc import Sequence
    from concurrent.futures import Future
    from pathlib import Path

    from PySide6.QtWidgets import QWidget

    from chatimport.commands import CommandResult
    from chatimport.gui.context import GuiContext
    from chatimport.gui.models.snapshot import ChatRow

_ = _chat_strings
TRIM_STEPS: Final = (25, 50, 75)


class ChatActions(QObject):
    """Stateless apart from the runner; `rows` is always the current selection."""

    def __init__(self, gui: GuiContext, page: QWidget) -> None:
        super().__init__(page)
        self._gui = gui
        self._page = page
        self._runner = MainThreadRunner(self)

    def pause(self, rows: Sequence[ChatRow]) -> None:
        self._send("pause", [r for r in rows if not r.is_paused] or list(rows))

    def resume(self, rows: Sequence[ChatRow]) -> None:
        self._send("resume", [r for r in rows if r.is_paused] or list(rows))

    def recheck(self, rows: Sequence[ChatRow]) -> None:
        self._send("recheck", rows)

    def deeper(self, rows: Sequence[ChatRow]) -> None:
        self._send("deeper", rows)

    def refetch(self, rows: Sequence[ChatRow]) -> None:
        text = plural(len(rows), "chats.confirm.refetch.text")
        if self._confirm(tr("chats.confirm.refetch.title"), text, tr("chats.confirm.refetch.yes")):
            self._send("refetch", rows)

    def trim(self, rows: Sequence[ChatRow], pct: int) -> None:
        text = plural(len(rows), "chats.confirm.trim.text", pct=pct)
        title = tr("chats.confirm.trim.title", pct=pct)
        if self._confirm(title, text, tr("chats.confirm.trim.yes")):
            self._send("trim", rows, {"pct": pct})

    def open_folder(self, row: ChatRow) -> None:
        root = self._gui.service.root
        self._runner.submit(lambda: find_chat_folder(root, row.chat_id), self._opened)

    def export(self, row: ChatRow) -> None:
        root = self._gui.service.root

        def work() -> Path | None:
            folder = find_chat_folder(root, row.chat_id)
            return None if folder is None else export_chat_json(folder, include_names=False)

        self._runner.submit(work, self._exported)

    def build_menu(self, rows: Sequence[ChatRow], parent: QWidget | None = None) -> QMenu:
        menu = QMenu(parent or self._page)
        single = len(rows) == 1
        have = bool(rows)
        self._add(menu, "pause", tr("chats.act.pause"), have, lambda: self.pause(rows))
        self._add(menu, "play", tr("chats.act.resume"), have, lambda: self.resume(rows))
        self._add(menu, "refresh", tr("chats.act.recheck"), have, lambda: self.recheck(rows))
        self._add(menu, "download", tr("chats.act.deeper"), have, lambda: self.deeper(rows))
        menu.addSeparator()
        self._add(menu, "refresh", tr("chats.act.refetch"), have, lambda: self.refetch(rows))
        trim = menu.addMenu(
            icon("trash", self._gui.theme.palette.fg_secondary, self._icon_px()),
            tr("chats.act.trim"),
        )
        trim.setEnabled(have)
        for pct in TRIM_STEPS:
            action = trim.addAction(tr("chats.act.trim_pct", pct=pct))
            action.triggered.connect(lambda _=False, p=pct: self.trim(rows, p))
        menu.addSeparator()
        self._add(
            menu, "folder-open", tr("chats.act.open"), single, lambda: self.open_folder(rows[0])
        )
        self._add(menu, "upload", tr("chats.act.export"), single, lambda: self.export(rows[0]))
        return menu

    def _icon_px(self) -> int:
        return self._gui.zoom.scaled(LAYOUT["icon_md"])

    def _add(self, menu: QMenu, icon_name: str, text: str, enabled: bool, call: Any) -> None:
        action = QAction(
            icon(icon_name, self._gui.theme.palette.fg_secondary, self._icon_px()), text, menu
        )
        action.setEnabled(enabled)
        action.triggered.connect(lambda _=False: call())
        menu.addAction(action)

    def _confirm(self, title: str, text: str, accept: str) -> bool:
        box = QMessageBox(self._page)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(text)
        yes = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is yes

    def _send(
        self, command: str, rows: Sequence[ChatRow], extra: dict[str, Any] | None = None
    ) -> None:
        if not rows:
            return
        pending = {"left": len(rows), "ok": 0, "unavailable": False}

        def finished(done: Future[CommandResult]) -> None:
            pending["left"] -= 1
            try:
                if done.result().ok:
                    pending["ok"] += 1
            except Exception:
                pending["unavailable"] = True
            if pending["left"]:
                return
            if pending["ok"]:
                notify(self._page, "success", plural(pending["ok"], f"chats.toast.{command}"))
            elif pending["unavailable"]:
                notify(self._page, "warning", tr("error.service_unavailable"))
            else:
                notify(self._page, "danger", tr("chats.toast.failed"))

        for row in rows:
            future = self._gui.bridge.execute(command, {"chat": row.chat_id, **(extra or {})})
            self._runner.watch(future, finished)

    def _opened(self, done: Future[Path | None]) -> None:
        folder = done.exception() or done.result()
        if isinstance(folder, BaseException) or folder is None:
            notify(self._page, "warning", tr("chats.toast.no_folder"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _exported(self, done: Future[Path | None]) -> None:
        result = done.exception() or done.result()
        if isinstance(result, BaseException):
            notify(self._page, "danger", tr("chats.toast.export_failed"))
        elif result is None:
            notify(self._page, "warning", tr("chats.toast.no_folder"))
        else:
            notify(self._page, "success", tr("chats.toast.export_ok", path=str(result)))
