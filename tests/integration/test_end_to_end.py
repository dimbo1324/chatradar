"""End-to-end scenarios: several workers over one scripted Telegram, the real router, folder
watcher, trimmer and recheck, with kills and restarts. Deterministic and free of real sleeps."""

from __future__ import annotations

import contextlib
import json
import shutil
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

import chatimport.storage.writer as writer
from chatimport.config import WatchConfig
from chatimport.guards.folders import FolderWatcher
from chatimport.offline import lower_floor_state
from chatimport.records import DETECTED_RECHECK, DeleteRecord, EditRecord
from chatimport.router import UNROUTED_DELETES_FILE, Router
from chatimport.runtime import ChatRegistry
from chatimport.storage.writer import iter_records
from chatimport.trim import Trimmer
from tests.fakes import CHAT_ID, NOW, FakeClock, FakeGateway, RecordingNotifier, msg
from tests.unit.worker.rig import (
    Rig,
    RigFactory,
    assert_disk_consistent,
    delete_event,
    make_rig,
    new_event,
    small_parts,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["make_rig", "small_parts"]

ALPHA, BETA, GAMMA = CHAT_ID, -1009999999991, -1009999999992


@dataclass
class World:
    gateway: FakeGateway
    clock: FakeClock
    notifier: RecordingNotifier
    rigs: dict[int, Rig]
    registry: ChatRegistry
    router: Router
    root: Path

    def trimmer(self) -> Trimmer:
        return Trimmer(self.root, self.registry, clock=self.clock, max_chunk_bytes=10**9)

    def watcher(self) -> FolderWatcher:
        return FolderWatcher(
            self.root,
            self.registry,
            WatchConfig(check_every_seconds=10, confirm_checks=2),
            clock=self.clock,
            notifier=self.notifier,
        )


def build_world(make_rig: RigFactory) -> World:
    gateway = FakeGateway()
    clock = FakeClock()
    notifier = RecordingNotifier()
    gateway.add_chat(ALPHA, range(1, 1001))
    gateway.add_chat(BETA, range(1, 51))
    gateway.add_chat(GAMMA, [])
    rigs = {
        chat_id: make_rig(
            chat_id=chat_id, title=title, gateway=gateway, clock=clock, notifier=notifier
        )
        for chat_id, title in ((ALPHA, "Alpha"), (BETA, "Beta"), (GAMMA, "Gamma"))
    }
    registry = ChatRegistry()
    for rig in rigs.values():
        registry.add(rig.worker)
    router = Router(registry, make_rig.root, clock=clock)
    gateway.add_event_handler(router.handle)
    return World(gateway, clock, notifier, rigs, registry, router, make_rig.root)


async def start_all(world: World) -> None:
    for rig in world.rigs.values():
        rig.start()
    for rig in world.rigs.values():
        await rig.until_complete()


async def test_three_chats_through_backfill_live_deletion_trim_deeper_and_recheck(
    make_rig: RigFactory,
) -> None:
    world = build_world(make_rig)
    alpha, beta, gamma = (world.rigs[c] for c in (ALPHA, BETA, GAMMA))

    await start_all(world)
    assert_disk_consistent(alpha.folder, expect_ids=range(1, 1001))
    assert_disk_consistent(beta.folder, expect_ids=range(1, 51))
    assert_disk_consistent(gamma.folder, expect_ids=[])
    assert world.gateway.handlers

    for i in range(1001, 1006):
        world.gateway.chats[ALPHA][i] = msg(i, chat_id=ALPHA)
        await world.gateway.fire(new_event(i, chat_id=ALPHA))
    for i in (51, 52):
        world.gateway.chats[BETA][i] = msg(i, chat_id=BETA)
        await world.gateway.fire(new_event(i, chat_id=BETA))
    await world.gateway.fire(new_event(1, chat_id=-777))
    await world.gateway.fire(delete_event([4, 5], None))
    await alpha.until(lambda: max(alpha.ids()) == 1005, "alpha flushed by count")
    await beta.settle()
    assert max(beta.ids()) == 50
    world.clock.advance(seconds=31)
    beta.worker.resume()
    await beta.until(lambda: max(beta.ids()) == 52, "beta flushed by time")

    unrouted = (world.root / UNROUTED_DELETES_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["msg_ids"] for line in unrouted] == [[4, 5]]
    assert not (world.root / "-777").exists()

    watcher = world.watcher()
    await watcher.check_once()
    shutil.rmtree(beta.folder)
    assert beta.load() is None
    await watcher.check_once()
    await beta.settle()
    assert beta.load() is None
    await watcher.check_once()
    await beta.until(
        lambda: beta.is_live() and beta.backfill_done() and beta.ids() == list(range(1, 53)),
        "beta refetched after its folder was deleted",
    )
    assert beta.state().floor_id == 0
    assert any("deleted" in n.message for n in world.notifier.notes)
    assert_disk_consistent(beta.folder, expect_ids=range(1, 53))

    report = await world.trimmer().trim_percent(50, ALPHA)
    assert report.per_chat == {ALPHA: 502}
    trimmed = alpha.state()
    assert (trimmed.floor_id, trimmed.floor_reason) == (503, "manual_trim_50")
    assert_disk_consistent(alpha.folder, expect_ids=range(503, 1006))
    assert_disk_consistent(beta.folder, expect_ids=range(1, 53))

    async with alpha.worker.lock:
        assert lower_floor_state(alpha.folder, world.clock.now())
    world.clock.advance(seconds=601)
    alpha.worker.resume()
    await alpha.until(
        lambda: alpha.is_live() and alpha.backfill_done() and alpha.ids() == list(range(1, 1006)),
        "alpha refilled below the old floor",
    )
    assert alpha.state().floor_id == 0
    assert_disk_consistent(alpha.folder, expect_ids=range(1, 1006))

    edited = world.gateway.chats[ALPHA][10]
    world.gateway.chats[ALPHA][10] = replace(
        edited, text="edited later", edit_date=NOW + timedelta(hours=2)
    )
    del world.gateway.chats[ALPHA][20]
    alpha.worker.request_recheck(60)
    await alpha.until(lambda: alpha.state().last_recheck_at is not None, "recheck recorded")

    found = [r for r in iter_records(alpha.folder) if isinstance(r, EditRecord | DeleteRecord)]
    assert [(type(r).__name__, r.detected_by) for r in found] == [
        ("EditRecord", DETECTED_RECHECK),
        ("DeleteRecord", DETECTED_RECHECK),
    ]
    assert isinstance(found[0], EditRecord)
    assert (found[0].msg_id, found[0].text) == (10, "edited later")
    assert isinstance(found[1], DeleteRecord)
    assert found[1].msg_ids == (20,)

    before = sum(1 for _ in iter_records(alpha.folder))
    alpha.worker.request_recheck(60)
    await alpha.until(lambda: alpha.state().last_recheck_at == world.clock.now(), "second recheck")
    assert sum(1 for _ in iter_records(alpha.folder)) == before

    for rig in world.rigs.values():
        await rig.worker.stop()
    assert_disk_consistent(gamma.folder, expect_ids=[])


async def test_a_deleted_data_root_is_recreated_and_every_chat_is_fetched_again(
    make_rig: RigFactory,
) -> None:
    world = build_world(make_rig)
    await start_all(world)
    watcher = world.watcher()
    await watcher.check_once()

    shutil.rmtree(world.root)
    await watcher.check_once()
    assert not world.root.exists()
    await watcher.check_once()
    assert world.root.is_dir()

    for chat_id, expected in ((ALPHA, range(1, 1001)), (BETA, range(1, 51))):
        rig = world.rigs[chat_id]
        await rig.until(
            lambda r=rig, e=expected: r.is_live() and r.backfill_done() and r.ids() == list(e),
            f"chat {chat_id} fetched again",
        )
        assert_disk_consistent(rig.folder, expect_ids=expected)


async def test_part_files_deleted_by_the_user_are_treated_as_a_trim_not_a_refetch(
    make_rig: RigFactory,
) -> None:
    world = build_world(make_rig)
    await start_all(world)
    alpha = world.rigs[ALPHA]
    watcher = world.watcher()
    await watcher.check_once()
    (alpha.folder / "2026-09_001.jsonl").unlink()

    await watcher.check_once()
    await watcher.check_once()

    state = alpha.state()
    assert (state.floor_id, state.floor_reason) == (316, "manual_delete")
    assert alpha.ids() == list(range(316, 1001))
    assert world.gateway.count("newest_id") == 3


class Lcg:
    def __init__(self, seed: int) -> None:
        self.value = seed * 7919 + 12345

    def below(self, bound: int) -> int:
        self.value = (self.value * 1103515245 + 12345) % 2**31
        return (self.value >> 8) % bound


@pytest.mark.parametrize("seed", range(10))
async def test_kill_and_restart_sequences_never_leave_gaps_or_duplicates(
    make_rig: RigFactory, small_parts: int, seed: int
) -> None:
    rng = Lcg(seed)
    gateway = FakeGateway()
    clock = FakeClock()
    gateway.add_chat(CHAT_ID, range(1, 301))
    next_id = 301

    for _ in range(6):
        for _ in range(rng.below(45)):
            gateway.chats[CHAT_ID][next_id] = msg(next_id)
            next_id += 1
        rig = make_rig(gateway=gateway, clock=clock)
        budget = 1 + rng.below(260)
        seen = 0

        def hook(rig: Rig = rig, budget: int = budget) -> None:
            nonlocal seen
            seen += 1
            if seen == budget and rig.task is not None:
                rig.task.cancel()

        gateway.page_hook = hook
        rig.start()
        for _ in range(60):
            await rig.settle(5)
            if rig.task is not None and rig.task.done():
                break
        else:
            for i in range(next_id - rng.below(6) - 1, next_id):
                if i in gateway.chats[CHAT_ID]:
                    rig.worker.submit(new_event(i))
            await rig.settle(rng.below(40))
        await rig.kill()
        gateway.page_hook = None
        if rig.load() is not None:
            assert_disk_consistent(rig.folder)

    final = make_rig(gateway=gateway, clock=clock)
    final.start()
    await final.until(
        lambda: (
            final.is_live()
            and final.backfill_done()
            and set(final.ids()) == set(gateway.chats[CHAT_ID])
        ),
        "everything stored",
    )
    assert_disk_consistent(final.folder, expect_ids=gateway.chats[CHAT_ID])


@pytest.mark.parametrize("target", ["atomic_write_bytes", "save_state"])
@pytest.mark.parametrize("nth", range(1, 17))
async def test_a_failure_at_any_single_write_loses_and_duplicates_nothing(
    make_rig: RigFactory,
    small_parts: int,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    nth: int,
) -> None:

    real = getattr(writer, target)
    calls = 0

    def flaky(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == nth:
            raise OSError("simulated crash")
        return real(*args)

    monkeypatch.setattr(f"chatimport.storage.writer.{target}", flaky)
    first = make_rig(range(1, 301))
    for attempt in range(2):
        with contextlib.suppress(OSError):
            await first.worker.sync_once()
        if attempt == 0:
            for i in range(301, 401):
                first.gateway.chats[CHAT_ID][i] = msg(i)

    second = make_rig(gateway=first.gateway, clock=first.clock)
    await second.worker.sync_once()
    await second.worker.sync_once()

    assert_disk_consistent(second.folder, expect_ids=range(1, 401))
    assert second.state().backfill.done
