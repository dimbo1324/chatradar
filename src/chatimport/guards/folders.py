"""Folder-deletion watcher (spec §8.4): refetch a deleted chat, recover a damaged one."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from chatimport.runtime import Level
from chatimport.storage.layout import list_parts
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import load_state

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import WatchConfig
    from chatimport.ports import Clock
    from chatimport.runtime import ChatController, ChatRegistry, Notifier

log = logging.getLogger(__name__)

TITLE: Final = "Folder watch"


class FolderWatcher:
    def __init__(
        self,
        root: Path,
        registry: ChatRegistry,
        config: WatchConfig,
        *,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._root = root
        self._registry = registry
        self._config = config
        self._clock = clock
        self._notifier = notifier
        self._root_seen = False
        self._root_misses = 0
        self._seen: set[int] = set()
        self._misses: dict[int, int] = {}
        self._refetching: set[int] = set()

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:
                log.exception("folder watcher check failed")
            await self._clock.sleep(self._config.check_every_seconds)

    async def check_once(self) -> None:
        if self._root.is_dir():
            self._root_seen = True
            self._root_misses = 0
        elif self._root_seen:
            self._root_misses += 1
            if self._root_misses >= self._config.confirm_checks:
                self._refetch_all()
            return
        else:
            return

        for controller in self._registry.all():
            await self._check_chat(controller)

    def _refetch_all(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._root_misses = 0
        for controller in self._registry.all():
            self._request_refetch(controller)
        self._notifier.notify(Level.WARNING, TITLE, "data folder was deleted, fetching again")

    def _request_refetch(self, controller: ChatController) -> None:
        chat_id = controller.chat_id
        self._misses[chat_id] = 0
        self._refetching.add(chat_id)
        controller.request_refetch()
        log.warning("chat folder deleted, refetch requested", extra={"chat_id": chat_id})

    async def _check_chat(self, controller: ChatController) -> None:
        chat_id = controller.chat_id
        folder = controller.folder
        if not folder.is_dir():
            if chat_id not in self._seen or chat_id in self._refetching:
                return
            misses = self._misses.get(chat_id, 0) + 1
            self._misses[chat_id] = misses
            if misses >= self._config.confirm_checks:
                self._request_refetch(controller)
                self._notifier.notify(
                    Level.WARNING, TITLE, f"folder of chat {chat_id} was deleted, fetching again"
                )
            return

        self._seen.add(chat_id)
        self._misses[chat_id] = 0
        self._refetching.discard(chat_id)
        async with controller.lock:
            if not folder.is_dir():
                return
            state = load_state(folder)
            parts = {p.stem for p in list_parts(folder)}
            if state is None:
                if not parts:
                    return
            elif set(state.chunks) == parts:
                return
            recover_chat(
                folder,
                now=self._clock.now(),
                fallback_chat_id=chat_id,
                fallback_title=controller.status().title,
            )
            log.warning("chat folder recovered after manual changes", extra={"chat_id": chat_id})
