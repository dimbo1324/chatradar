from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from chatimport.config import MediaConfig
from chatimport.media import DOWNLOAD_PAUSE_SECONDS, IDLE_SECONDS, MAX_ATTEMPTS, MediaDownloader
from chatimport.ports import AccessLost, FloodWait
from chatimport.records import MediaInfo, MediaSavedRecord, MessageRecord, Record
from chatimport.runtime import ChatRegistry
from chatimport.storage.layout import STATE_FILE, list_parts
from chatimport.storage.state import save_state
from chatimport.storage.writer import ChunkWriter, iter_records
from tests.fakes import NOW, FakeClock, FakeGateway
from tests.unit.maintenance.helpers import FakeController, at, build_chat, drive, read_state

if TYPE_CHECKING:
    from pathlib import Path

MIB = 1024 * 1024
CHAT = -100


def photo(size: int | None = 100, kind: str = "photo") -> MediaInfo:
    return MediaInfo(type=kind, size=size)


def media_msg(
    msg_id: int, info: MediaInfo | None = None, *, chat_id: int = CHAT, month: int = 9
) -> MessageRecord:
    return MessageRecord(
        chat_id=chat_id,
        msg_id=msg_id,
        date=at(2026, month, 10, msg_id % 24),
        fetched_at=NOW,
        text="m",
        media=info or photo(),
    )


def drop_file(target_dir: Path, name: str, data: bytes) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_bytes(data)
    return path


def saved(chat: FakeController) -> list[MediaSavedRecord]:
    return [r for r in iter_records(chat.folder) if isinstance(r, MediaSavedRecord)]


def setup(
    root: Path,
    batches: list[list[Record]],
    *,
    chat_id: int = CHAT,
    types: tuple[str, ...] = ("photo",),
    max_file_mb: int = 50,
    enabled: bool = True,
    title: str = "Chat",
) -> tuple[MediaDownloader, FakeController, FakeGateway, FakeClock, ChatRegistry]:
    chat = build_chat(root, chat_id, batches, title=title)
    registry = ChatRegistry()
    registry.add(chat)
    gateway = FakeGateway()
    clock = FakeClock()
    config = MediaConfig(enabled=enabled, types=types, max_file_mb=max_file_mb)
    downloader = MediaDownloader(registry, gateway, config, clock=clock, max_chunk_bytes=1)
    return downloader, chat, gateway, clock, registry


def provide(gateway: FakeGateway, chat_id: int, *ids: int) -> None:
    for msg_id in ids:
        gateway.media[(chat_id, msg_id)] = f"bytes {msg_id}".encode()


async def test_every_pending_media_is_downloaded_in_id_order_and_recorded_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(3), media_msg(1), media_msg(2)]])
    provide(gateway, CHAT, 1, 2, 3)

    await drive(dl.run, clock, cycles=6)

    assert [c[1][1] for c in gateway.calls if c[0] == "download_media"] == [1, 2, 3]
    records = saved(chat)
    assert [r.msg_id for r in records] == [1, 2, 3]
    assert [r.file for r in records] == [
        "media/2026-09/1.bin",
        "media/2026-09/2.bin",
        "media/2026-09/3.bin",
    ]
    month_dir = chat.folder / "media" / "2026-09"
    assert sorted(p.name for p in month_dir.iterdir()) == ["1.bin", "2.bin", "3.bin"]
    assert (month_dir / "2.bin").read_bytes() == b"bytes 2"
    assert all(r.fetched_at >= NOW for r in records)


async def test_pauses_follow_each_download_and_idle_follows_an_empty_cycle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    dl, _, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1)

    await drive(dl.run, clock, cycles=3)

    assert clock.sleeps == [DOWNLOAD_PAUSE_SECONDS, IDLE_SECONDS, IDLE_SECONDS]


async def test_a_second_downloader_does_not_download_again(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, registry = setup(root, [[media_msg(1), media_msg(2)]])
    provide(gateway, CHAT, 1, 2)
    await drive(dl.run, clock, cycles=4)
    assert gateway.count("download_media") == 2

    gateway2 = FakeGateway(media=dict(gateway.media))
    clock2 = FakeClock()
    other = MediaDownloader(
        registry,
        gateway2,
        MediaConfig(enabled=True, types=("photo",)),
        clock=clock2,
        max_chunk_bytes=1,
    )
    await drive(other.run, clock2, cycles=3)

    assert gateway2.count("download_media") == 0
    assert len(saved(chat)) == 2


@pytest.mark.parametrize(
    ("types", "kind"),
    [
        (("photo",), "video"),
        ((), "photo"),
        (("video", "voice"), "photo"),
        (("photo",), "Photo"),
    ],
)
async def test_media_types_that_are_not_configured_are_skipped(
    tmp_path: Path, types: tuple[str, ...], kind: str
) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1, photo(kind=kind))]], types=types)
    provide(gateway, CHAT, 1)

    await drive(dl.run, clock, cycles=3)

    assert gateway.count("download_media") == 0
    assert saved(chat) == []
    assert clock.sleeps == [IDLE_SECONDS] * 3


@pytest.mark.parametrize(
    ("size", "downloaded"),
    [
        (5 * MIB - 1, True),
        (5 * MIB, True),
        (5 * MIB + 1, False),
        (None, True),
        (0, True),
    ],
)
async def test_size_limit_is_inclusive_and_unknown_size_is_allowed(
    tmp_path: Path, size: int | None, downloaded: bool
) -> None:
    root = tmp_path / "root"
    dl, _, gateway, clock, _ = setup(root, [[media_msg(1, photo(size))]], max_file_mb=5)
    provide(gateway, CHAT, 1)

    await drive(dl.run, clock, cycles=2)

    assert (gateway.count("download_media") == 1) is downloaded


async def test_messages_below_the_floor_are_not_downloaded(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1), media_msg(2), media_msg(3)]])
    save_state(chat.folder, replace(read_state(chat), floor_id=2))
    provide(gateway, CHAT, 1, 2, 3)

    await drive(dl.run, clock, cycles=5)

    assert [r.msg_id for r in saved(chat)] == [2, 3]


async def test_unique_names_when_the_final_name_is_taken(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(7)]])
    provide(gateway, CHAT, 7)
    month_dir = chat.folder / "media" / "2026-09"
    month_dir.mkdir(parents=True)
    (month_dir / "7.bin").write_bytes(b"old")
    (month_dir / "7_1.bin").write_bytes(b"older")

    await drive(dl.run, clock, cycles=2)

    (record,) = saved(chat)
    assert record.file == "media/2026-09/7_2.bin"
    assert (month_dir / "7.bin").read_bytes() == b"old"
    assert (month_dir / "7_2.bin").read_bytes() == b"bytes 7"


async def test_the_extension_of_the_downloaded_file_is_kept(tmp_path: Path) -> None:
    root = tmp_path / "root"

    class JpgGateway(FakeGateway):
        async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
            path = drop_file(target_dir, f"photo_{msg_id}.jpg", b"jpg")
            return path

    dl, chat, _, clock, _ = setup(root, [[media_msg(5)]])
    dl._gateway = JpgGateway()  # pyright: ignore[reportPrivateUsage]

    await drive(dl.run, clock, cycles=2)

    (record,) = saved(chat)
    assert record.file == "media/2026-09/5.jpg"


async def test_media_of_each_month_goes_to_its_own_folder(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(
        root, [[media_msg(1, month=8)], [media_msg(2, month=9)], [media_msg(3, month=12)]]
    )
    provide(gateway, CHAT, 1, 2, 3)

    await drive(dl.run, clock, cycles=6)

    assert [r.file for r in saved(chat)] == [
        "media/2026-08/1.bin",
        "media/2026-09/2.bin",
        "media/2026-12/3.bin",
    ]


async def test_unavailable_media_is_not_retried_forever(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1), media_msg(2)]])
    provide(gateway, CHAT, 2)

    await drive(dl.run, clock, cycles=10)

    assert gateway.count("download_media") == 2
    assert [r.msg_id for r in saved(chat)] == [2]


async def test_flood_wait_sleeps_the_requested_time_then_retries(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1)
    gateway.fail["download_media"] = [FloodWait(77)]

    await drive(dl.run, clock, cycles=4)

    assert 77 in clock.sleeps
    assert gateway.count("download_media") == 2
    assert [r.msg_id for r in saved(chat)] == [1]


async def test_flood_wait_does_not_consume_an_attempt(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1)
    gateway.fail["download_media"] = [FloodWait(1)] * (MAX_ATTEMPTS + 2)

    await drive(dl.run, clock, cycles=30)

    assert [r.msg_id for r in saved(chat)] == [1]


async def test_access_lost_skips_that_chat_for_good_and_others_continue(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat_a, gateway, clock, registry = setup(
        root, [[media_msg(1), media_msg(2)]], chat_id=-1, title="A"
    )
    chat_b = build_chat(root, -2, [[media_msg(5, chat_id=-2)]], title="B")
    registry.add(chat_b)
    provide(gateway, -1, 1, 2)
    provide(gateway, -2, 5)
    gateway.fail["download_media"] = [AccessLost(-1)]

    await drive(dl.run, clock, cycles=10)

    assert saved(chat_a) == []
    assert [r.msg_id for r in saved(chat_b)] == [5]
    chats_called = [c[1][0] for c in gateway.calls if c[0] == "download_media"]
    assert chats_called.count(-1) == 1


async def test_generic_failures_are_retried_at_most_three_times_per_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1), media_msg(2)]])
    provide(gateway, CHAT, 1, 2)
    gateway.fail["download_media"] = [RuntimeError("boom")] * 20

    with caplog.at_level("WARNING"):
        await drive(dl.run, clock, cycles=15)

    calls = [c[1][1] for c in gateway.calls if c[0] == "download_media"]
    assert calls == [1] * MAX_ATTEMPTS + [2] * MAX_ATTEMPTS
    assert saved(chat) == []
    assert caplog.text.count("media download failed") == 2 * MAX_ATTEMPTS


async def test_a_failing_file_does_not_block_the_next_one_after_the_cap(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1), media_msg(2)]])
    provide(gateway, CHAT, 2)
    gateway.fail["download_media"] = [RuntimeError("boom")] * MAX_ATTEMPTS

    await drive(dl.run, clock, cycles=12)

    assert [r.msg_id for r in saved(chat)] == [2]
    calls = [c[1][1] for c in gateway.calls if c[0] == "download_media"]
    assert calls.count(1) == MAX_ATTEMPTS


async def test_state_vanishing_during_the_download_deletes_the_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, _, clock, _ = setup(root, [[media_msg(1)]])

    class VanishingGateway(FakeGateway):
        async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
            path = drop_file(target_dir, "tmp.bin", b"x")
            (chat.folder / STATE_FILE).unlink(missing_ok=True)
            return path

    dl._gateway = VanishingGateway()  # pyright: ignore[reportPrivateUsage]

    await drive(dl.run, clock, cycles=3)

    media_dir = chat.folder / "media" / "2026-09"
    assert list(media_dir.iterdir()) == []
    assert saved(chat) == []


async def test_floor_rising_during_the_download_deletes_the_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, _, clock, _ = setup(root, [[media_msg(1), media_msg(2)]])

    class RaisingGateway(FakeGateway):
        async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
            path = drop_file(target_dir, f"t{msg_id}.bin", b"x")
            save_state(chat.folder, replace(read_state(chat), floor_id=100))
            return path

    dl._gateway = RaisingGateway()  # pyright: ignore[reportPrivateUsage]

    await drive(dl.run, clock, cycles=4)

    assert list((chat.folder / "media" / "2026-09").iterdir()) == []
    assert saved(chat) == []


@pytest.mark.parametrize("mode", ["disabled", "paused", "empty_registry"])
async def test_idle_modes_download_nothing_and_sleep_five_seconds(
    tmp_path: Path, mode: str
) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, registry = setup(root, [[media_msg(1)]], enabled=mode != "disabled")
    provide(gateway, CHAT, 1)
    if mode == "paused":
        dl.pause()
        assert dl.paused
    if mode == "empty_registry":
        registry.remove(CHAT)

    await drive(dl.run, clock, cycles=4)

    assert gateway.count("download_media") == 0
    assert clock.sleeps == [IDLE_SECONDS] * 4
    assert saved(chat) == []


async def test_resume_continues_after_pause(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1)
    dl.pause()
    await drive(dl.run, clock, cycles=2)
    assert saved(chat) == []

    dl.resume()
    assert not dl.paused
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=2)

    assert [r.msg_id for r in saved(chat)] == [1]


async def test_pausing_during_a_round_robin_stops_before_the_next_chat(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    holder: list[MediaDownloader] = []

    class PausingController(FakeController):
        @property
        def folder(self) -> Path:
            holder[0].pause()
            return super().folder

    dl, real, gateway, clock, registry = setup(root, [[media_msg(2, chat_id=-2)]], chat_id=-2)
    quiet_folder = build_chat(root, -1, [[]], title="A").folder
    registry.remove(-2)
    registry.add(PausingController(-1, quiet_folder, "A"))
    registry.add(real)
    holder.append(dl)
    provide(gateway, -2, 2)

    assert await dl._download_next() is False  # pyright: ignore[reportPrivateUsage]

    assert gateway.count("download_media") == 0
    assert saved(real) == []
    assert clock.sleeps == []


async def test_round_robin_alternates_between_chats(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, _, gateway, clock, registry = setup(
        root, [[media_msg(1), media_msg(2)]], chat_id=-1, title="A"
    )
    registry.add(build_chat(root, -2, [[media_msg(11, chat_id=-2), media_msg(12, chat_id=-2)]]))
    provide(gateway, -1, 1, 2)
    provide(gateway, -2, 11, 12)

    await drive(dl.run, clock, cycles=4)

    order = [c[1] for c in gateway.calls if c[0] == "download_media"]
    assert order == [(-1, 1), (-2, 11), (-1, 2), (-2, 12)]


async def test_a_chat_without_pending_media_does_not_stall_the_others(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, _, gateway, clock, registry = setup(root, [[]], chat_id=-1, title="A")
    registry.add(build_chat(root, -2, [[media_msg(11, chat_id=-2)]], title="B"))
    registry.add(build_chat(root, -3, [[media_msg(21, chat_id=-3)]], title="C"))
    provide(gateway, -2, 11)
    provide(gateway, -3, 21)

    await drive(dl.run, clock, cycles=4)

    order = [c[1] for c in gateway.calls if c[0] == "download_media"]
    assert order == [(-2, 11), (-3, 21)]


async def test_media_appended_to_the_last_part_is_found_by_the_rescan(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1, 2)
    await drive(dl.run, clock, cycles=3)
    assert [r.msg_id for r in saved(chat)] == [1]

    ChunkWriter(chat.folder, 10**9).append(read_state(chat), [media_msg(2, month=10)])
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=3)

    assert [r.msg_id for r in saved(chat)] == [1, 2]


async def test_media_appended_to_a_new_later_part_is_found_by_the_rescan(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1, 2)
    await drive(dl.run, clock, cycles=3)

    ChunkWriter(chat.folder, 1).append(read_state(chat), [media_msg(2, month=12)])
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=3)

    assert [r.msg_id for r in saved(chat)] == [1, 2]


async def test_media_added_to_an_earlier_part_is_found_by_the_rescan(tmp_path: Path) -> None:
    """A message dated 30 Sep that is flushed after midnight lands in the September part
    although an October part (the media_saved record) already exists."""
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1, 2)
    await drive(dl.run, clock, cycles=3)
    assert [p.name for p in list_parts(chat.folder)] == ["2026-09_001.jsonl", "2026-10_001.jsonl"]

    ChunkWriter(chat.folder, 10**9).append(read_state(chat), [media_msg(2, month=9)])
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=3)

    assert [r.msg_id for r in saved(chat)] == [1, 2]


async def test_a_chat_without_a_readable_state_is_not_downloaded(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(root, [[media_msg(1)]])
    provide(gateway, CHAT, 1)
    (chat.folder / STATE_FILE).unlink()

    await drive(dl.run, clock, cycles=6)

    assert gateway.count("download_media") == 0


async def test_a_file_already_named_by_its_message_id_is_kept_as_it_is(tmp_path: Path) -> None:
    root = tmp_path / "root"

    class NamedGateway(FakeGateway):
        async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
            path = drop_file(target_dir, f"{msg_id}.jpg", b"j")
            return path

    dl, chat, _, clock, _ = setup(root, [[media_msg(8)]])
    dl._gateway = NamedGateway()  # pyright: ignore[reportPrivateUsage]

    await drive(dl.run, clock, cycles=2)

    assert [r.file for r in saved(chat)] == ["media/2026-09/8.jpg"]


async def test_deleting_the_oldest_part_resets_the_scan_without_redownloading(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    dl, chat, gateway, clock, _ = setup(
        root, [[media_msg(1, month=7)], [media_msg(2, month=8)], [media_msg(3, month=9)]]
    )
    provide(gateway, CHAT, 1, 2, 3, 4)
    await drive(dl.run, clock, cycles=7)
    assert gateway.count("download_media") == 3

    list_parts(chat.folder)[0].unlink()
    state = read_state(chat)
    save_state(chat.folder, replace(state, floor_id=2))
    ChunkWriter(chat.folder, 1).append(read_state(chat), [media_msg(4, month=10)])
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=4)

    calls = [c[1][1] for c in gateway.calls if c[0] == "download_media"]
    assert calls == [1, 2, 3, 4]


async def test_media_saved_marks_found_in_a_later_part_cancel_pending_downloads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    mark = MediaSavedRecord(CHAT, 1, "media/2026-09/1.bin", NOW)
    dl, _, gateway, clock, _ = setup(root, [[media_msg(1)], [media_msg(2)], [mark]])
    provide(gateway, CHAT, 1, 2)

    await drive(dl.run, clock, cycles=4)

    calls = [c[1][1] for c in gateway.calls if c[0] == "download_media"]
    assert calls == [2]


async def test_messages_without_media_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "root"
    plain = MessageRecord(CHAT, 1, at(2026, 9, 1), NOW, text="hi")
    dl, _, gateway, clock, _ = setup(root, [[plain]])
    provide(gateway, CHAT, 1)

    await drive(dl.run, clock, cycles=2)

    assert gateway.count("download_media") == 0
