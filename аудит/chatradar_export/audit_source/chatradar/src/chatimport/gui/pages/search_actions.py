"""What can be done with a found message: copy its text or link, open it in Telegram."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

from chatimport.gui.i18n import tr
from chatimport.gui.pages.support import notify

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.search_types import SearchHit


def copy_text(widget: QWidget, hit: SearchHit) -> None:
    QGuiApplication.clipboard().setText(hit.text)
    notify(widget, "success", tr("find.toast.text_copied"))


def copy_link(widget: QWidget, hit: SearchHit) -> None:
    if hit.link is not None:
        QGuiApplication.clipboard().setText(hit.link)
        notify(widget, "success", tr("find.toast.link_copied"))


def open_link(widget: QWidget, hit: SearchHit) -> None:
    if hit.link is not None and not QDesktopServices.openUrl(QUrl(hit.link)):
        notify(widget, "danger", tr("find.toast.open_failed"))
