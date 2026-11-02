"""The thread the search backend lives on.

SQLite connections belong to the thread that opened them, so one dedicated thread opens, uses
and closes the backend; every job runs there in order. The backend is opened lazily on the
first job, again after the data root changed, and again later when the index file did not exist
yet (the factory then answered `None`).
"""

from __future__ import annotations

import importlib
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from chatimport.search_types import SearchBackend

log = logging.getLogger(__name__)

THREAD_NAME: Final = "gui-search"

type BackendFactory = Callable[[Path], SearchBackend | None]


def default_backend_factory(root: Path) -> SearchBackend | None:
    """Open the read-only index under `root`, or `None` when the module or the file is missing."""
    try:
        module = importlib.import_module("chatimport.search_index")
    except ImportError:
        return None
    opener = getattr(module, "open_reader", None)
    if not callable(opener):
        return None
    return cast("SearchBackend | None", opener(root))


class SearchWorker:
    def __init__(self, root: Callable[[], Path], factory: BackendFactory) -> None:
        self._root = root
        self._factory = factory
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=THREAD_NAME)
        self._backend: SearchBackend | None = None
        self._opened_for: Path | None = None
        self._closed = False

    def run[T](self, job: Callable[[SearchBackend | None], T]) -> Future[T]:
        """Run `job(backend)` on the worker thread; the backend is `None` without an index."""
        if self._closed:
            dead: Future[T] = Future()
            dead.cancel()
            return dead
        return self._pool.submit(self._call, job)

    def _call[T](self, job: Callable[[SearchBackend | None], T]) -> T:
        return job(self._ensure())

    def _ensure(self) -> SearchBackend | None:
        root = self._root()
        if self._backend is not None and self._opened_for != root:
            self._drop()
        if self._backend is None:
            self._backend = self._factory(root)
            self._opened_for = root
        return self._backend

    def _drop(self) -> None:
        backend, self._backend = self._backend, None
        if backend is None:
            return
        try:
            backend.close()
        except Exception as error:
            log.warning("closing the search index failed: %s", type(error).__name__)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.submit(self._drop)
        self._pool.shutdown(wait=False)
