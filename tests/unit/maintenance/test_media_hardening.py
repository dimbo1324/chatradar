from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport import media as media_module
from chatimport.records import MediaInfo, Record
from chatimport.storage.layout import STATE_FILE, list_parts
from chatimport.storage.writer import ChunkWriter
from tests.fakes import FakeGateway
from tests.unit.maintenance.helpers import drive, read_state
from tests.unit.maintenance.test_media import (
    CHAT,
    drop_file,
    media_msg,
    provide,
    saved,
    setup,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


async def test_media_executable_suffix_is_neutralised(tmp_path: Path) -> None:
    class ExeGateway(FakeGateway):
        async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
            return drop_file(target_dir, "x.exe", b"MZ")

    dl, chat, _, clock, _ = setup(
        tmp_path / "root", [[media_msg(4, MediaInfo(type="document", size=2))]], types=("document",)
    )
    dl._gateway = ExeGateway()  # pyright: ignore[reportPrivateUsage]
    await drive(dl.run, clock, cycles=2)
    (record,) = saved(chat)
    assert record.file == "media/2026-09/4.exe.bin"
    assert (chat.folder / record.file).read_bytes() == b"MZ"


def count_reads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    reads: list[tuple[str, int]] = []
    real = media_module.read_appended

    def spy(path: Path, start: int) -> tuple[list[Record], int]:
        reads.append((path.name, start))
        return real(path, start)

    monkeypatch.setattr(media_module, "read_appended", spy)
    return reads


async def test_media_scan_reads_only_appended_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dl, chat, gateway, clock, _ = setup(tmp_path / "root", [[media_msg(1)]])
    provide(gateway, CHAT, 1, 2)
    reads = count_reads(monkeypatch)
    await drive(dl.run, clock, cycles=3)
    assert [r.msg_id for r in saved(chat)] == [1]

    reads.clear()
    part = list_parts(chat.folder)[-1]
    size = part.stat().st_size
    ChunkWriter(chat.folder, 10**9).append(read_state(chat), [media_msg(2, month=10)])
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=3)

    assert [r.msg_id for r in saved(chat)] == [1, 2]
    assert reads[0] == (part.name, size)


async def test_a_rewrite_of_the_last_part_triggers_a_full_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dl, chat, gateway, clock, _ = setup(tmp_path / "root", [[media_msg(1)], [media_msg(2)]])
    provide(gateway, CHAT, 1, 2, 3)
    await drive(dl.run, clock, cycles=4)
    assert [r.msg_id for r in saved(chat)] == [1, 2]

    reads = count_reads(monkeypatch)
    last = list_parts(chat.folder)[-1]
    replacement = last.with_name(".rewrite.tmp")
    replacement.write_bytes(last.read_bytes())
    replacement.replace(last)
    clock.sleeps.clear()
    await drive(dl.run, clock, cycles=2)

    assert reads[0][1] == 0
    assert {name for name, _ in reads} == {p.name for p in list_parts(chat.folder)}
    assert gateway.count("download_media") == 2


async def test_an_unreadable_state_skips_the_chat_for_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path as RealPath

    dl, _, gateway, clock, _ = setup(tmp_path / "root", [[media_msg(1)]])
    provide(gateway, CHAT, 1)
    real = RealPath.read_bytes

    def locked(self: RealPath) -> bytes:
        if self.name == STATE_FILE:
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(RealPath, "read_bytes", locked)
    await drive(dl.run, clock, cycles=3)
    assert gateway.count("download_media") == 0
