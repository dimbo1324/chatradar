"""The control flags of one chat worker and the gates built from them.

Only the controller methods (`pause`, `resume`, `stop`, ...) set the flags; the worker's
phases read them at safe points through `raise_if_interrupted` and `wait_backfill_gate`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class Stop(Exception):
    """The worker was asked to stop."""


class Refetch(Exception):
    """The chat folder was deleted: start again from the head backfill."""


class WorkerSignals:
    def __init__(self, wake: Callable[[], None]) -> None:
        self._wake = wake
        self.stopping = False
        self.paused = False
        self.backfill_paused = False
        self.refetch = False
        self.pause_decided = False
        self.tail_check = False
        self.resumed = asyncio.Event()
        self.resumed.set()
        self._backfill_gate = asyncio.Event()
        self._backfill_gate.set()

    def pause(self) -> None:
        self.pause_decided = True
        self.paused = True
        self.resumed.clear()
        self._update_gate()
        self._wake()

    def resume(self) -> None:
        self.pause_decided = True
        self.paused = False
        self.resumed.set()
        self._update_gate()
        self._wake()

    def restore_pause(self) -> None:
        """Keep a pause recorded in `state.json` by an earlier run, unless the owner has
        already paused or resumed this worker."""
        if not self.pause_decided:
            self.pause()

    def pause_backfill(self) -> None:
        self.backfill_paused = True
        self._update_gate()

    def resume_backfill(self) -> None:
        self.backfill_paused = False
        self.tail_check = True
        self._update_gate()
        self._wake()

    def request_refetch(self) -> None:
        self.refetch = True
        self._update_gate()
        self._wake()

    def clear_refetch(self) -> None:
        self.refetch = False
        self._update_gate()

    def stop(self) -> None:
        self.stopping = True
        self.resumed.set()
        self._update_gate()
        self._wake()

    def take_tail_check(self) -> bool:
        requested, self.tail_check = self.tail_check, False
        return requested

    def raise_if_interrupted(self) -> None:
        if self.stopping:
            raise Stop
        if self.refetch:
            raise Refetch

    @property
    def backfill_open(self) -> bool:
        self.raise_if_interrupted()
        return self._backfill_gate.is_set()

    async def wait_backfill_gate(self) -> None:
        while not self.backfill_open:
            await self._backfill_gate.wait()

    def _update_gate(self) -> None:
        if not (self.paused or self.backfill_paused) or self.stopping or self.refetch:
            self._backfill_gate.set()
        else:
            self._backfill_gate.clear()
