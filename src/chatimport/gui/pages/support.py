"""Plumbing the pages share: the toast host lookup and work that finishes on the main thread.

The service lives on its own thread, so every `Future` it returns completes elsewhere. Qt
objects may only be touched from the main thread, so completion callbacks are posted through a
queued signal and run there.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, Signal

from chatimport.gui.widgets.toast import ToastHost

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from PySide6.QtWidgets import QLayout, QWidget

    from chatimport.gui.widgets.base import Tone

THREAD_PREFIX: Final = "gui-task"


def find_toasts(widget: QWidget) -> ToastHost | None:
    return widget.window().findChild(ToastHost)


def clear_layout(layout: QLayout) -> None:
    """Remove every widget at once (`deleteLater` alone leaves them painted until the next loop)."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def notify(widget: QWidget, tone: Tone, message: str) -> None:
    host = find_toasts(widget)
    if host is not None:
        host.push(tone, message)


class MainThreadRunner(QObject):
    """`submit` runs `func` on a worker thread; `on_done` gets the finished future on the main one.

    `watch` does the same for a future somebody else created (the service bridge's).
    """

    _post = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix=THREAD_PREFIX)
        self._post.connect(self._invoke)

    def _invoke(self, call: object) -> None:
        if callable(call):
            call()

    def watch[T](self, future: Future[T], on_done: Callable[[Future[T]], None]) -> None:
        future.add_done_callback(lambda done: self._post.emit(lambda: on_done(done)))

    def submit[T](self, func: Callable[[], T], on_done: Callable[[Future[T]], None]) -> Future[T]:
        future = self._pool.submit(func)
        self.watch(future, on_done)
        return future

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
