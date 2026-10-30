from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import status as status_module
from chatimport.runtime import ChatRegistry, ChatStatus
from chatimport.status import GB, STATUS_FILE, StatusWriter, format_status_lines
from chatimport.supervisor import Supervisor
from tests.fakes import CHAT_ID, FakeClock, FakeDisk, RecordingNotifier
from tests.unit.service.helpers import StubController

if TYPE_CHECKING:
    from pathlib import Path


def tmp_leftovers(folder: Path) -> list[str]:
    return [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]


TITLE = "".join(chr(code) for code in (0x427, 0x430, 0x442)) + " ☃ 😀"


class Setup:
    def __init__(self, root: Path, free: int = 41 * GB) -> None:
        self.root = root
        self.registry = ChatRegistry()
        self.clock = FakeClock()
        self.supervisor = Supervisor(self.clock, RecordingNotifier())
        self.state = "running"
        self.writer = StatusWriter(
            root,
            self.registry,
            self.supervisor,
            clock=self.clock,
            disk=FakeDisk(free),
            low_watermark_gb=15,
            service_state=lambda: self.state,
        )


def test_build_has_the_shape_of_the_spec(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    controller = StubController(CHAT_ID, title="Example group")
    controller.last_id = 4512
    controller.records = 48210
    setup.registry.add(controller)

    data = setup.writer.build(total_bytes=2254857830)

    assert data == {
        "updated_at": "2026-10-29T12:00:00Z",
        "service": "running",
        "disk": {"path": str(tmp_path), "free_gb": 41.0, "low_watermark_gb": 15},
        "total_bytes": 2254857830,
        "chats": [
            {
                "chat_id": CHAT_ID,
                "title": "Example group",
                "phase": "live",
                "last_id": 4512,
                "backfill_done": True,
                "oldest_date": None,
                "records": 48210,
                "paused": False,
            }
        ],
        "errors": [],
    }
    json.dumps(data)


def test_build_renders_oldest_date_as_utc_z(tmp_path: Path) -> None:
    class Dated(StubController):
        def status(self) -> ChatStatus:
            base = super().status()
            return ChatStatus(
                chat_id=base.chat_id,
                title=base.title,
                phase=base.phase,
                last_id=1,
                backfill_done=False,
                oldest_date=datetime(2024, 3, 2, 8, 14, 55, tzinfo=UTC),
                records=0,
                paused=True,
            )

    setup = Setup(tmp_path)
    setup.registry.add(Dated(1))

    chat = setup.writer.build(0)["chats"][0]

    assert chat["oldest_date"] == "2024-03-02T08:14:55Z"
    assert chat["paused"] is True
    assert chat["backfill_done"] is False


def test_chat_error_is_included_only_when_set(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    ok, bad = StubController(1), StubController(2)
    bad.error = "FloodWait"
    setup.registry.add(ok)
    setup.registry.add(bad)

    chats = setup.writer.build(0)["chats"]

    assert "error" not in chats[0]
    assert chats[1]["error"] == "FloodWait"


@pytest.mark.parametrize(
    ("free_bytes", "expected"),
    [
        (0, 0.0),
        (int(0.06 * GB), 0.1),
        (GB // 40, 0.0),
        (int(41.25 * GB), 41.2),
        (int(41.26 * GB), 41.3),
    ],
)
def test_free_space_is_rounded_to_one_decimal_gib(
    tmp_path: Path, free_bytes: int, expected: float
) -> None:
    setup = Setup(tmp_path, free=free_bytes)

    assert setup.writer.build(0)["disk"]["free_gb"] == pytest.approx(expected)


def test_total_bytes_counts_only_jsonl_files_recursively(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "x.jsonl").write_bytes(b"1234")
    (tmp_path / "a" / "2026-10_001.jsonl").write_bytes(b"12345678")
    (tmp_path / "a" / "b" / "deep.jsonl").write_bytes(b"1")
    (tmp_path / "a" / "state.json").write_bytes(b"x" * 100)
    (tmp_path / "a" / "photo.jpg").write_bytes(b"x" * 100)
    (tmp_path / "a" / "2026-10_001.jsonl.tmp").write_bytes(b"x" * 100)
    (tmp_path / "_status.json").write_bytes(b"x" * 100)

    assert Setup(tmp_path).writer.build()["total_bytes"] == 13


def test_total_bytes_of_a_missing_root_is_zero(tmp_path: Path) -> None:
    assert Setup(tmp_path / "missing").writer.build()["total_bytes"] == 0


def test_total_bytes_ignores_a_directory_named_like_a_jsonl_file(tmp_path: Path) -> None:
    (tmp_path / "weird.jsonl").mkdir()
    (tmp_path / "weird.jsonl" / "inner.jsonl").write_bytes(b"123")

    assert Setup(tmp_path).writer.build()["total_bytes"] == 3


def test_errors_merge_supervisor_and_manual_with_manual_winning_same_key(
    tmp_path: Path,
) -> None:
    setup = Setup(tmp_path)
    setup.supervisor._errors["worker-1"] = "RuntimeError: a"  # pyright: ignore[reportPrivateUsage]
    setup.supervisor._errors["library"] = "old"  # pyright: ignore[reportPrivateUsage]
    setup.writer.add_error("library", "new")
    setup.writer.add_error("resolve:x", "unresolved")

    errors = setup.writer.build(0)["errors"]

    assert errors == [
        {"source": "worker-1", "message": "RuntimeError: a"},
        {"source": "library", "message": "new"},
        {"source": "resolve:x", "message": "unresolved"},
    ]


def test_clear_error_removes_it_and_unknown_keys_are_ignored(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.writer.add_error("k", "m")
    setup.writer.clear_error("k")
    setup.writer.clear_error("never-added")

    assert setup.writer.build(0)["errors"] == []


def test_service_state_is_read_at_build_time(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.state = "stopping"

    assert setup.writer.build(0)["service"] == "stopping"


async def test_write_creates_status_file_with_utf8_and_leaves_no_temp(tmp_path: Path) -> None:
    root = tmp_path / "ChatImport"
    root.mkdir()
    setup = Setup(root)
    setup.registry.add(StubController(1, title=TITLE))
    (root / "a.jsonl").write_bytes(b"12345")

    await setup.writer.write()

    raw = (root / STATUS_FILE).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    assert data["total_bytes"] == 5
    assert data["chats"][0]["title"] == TITLE
    assert TITLE.encode() in raw
    assert sorted(p.name for p in root.iterdir()) == ["_status.json", "a.jsonl"]


async def test_write_does_nothing_when_root_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "gone"
    setup = Setup(root)

    await setup.writer.write()

    assert not root.exists()


async def test_write_replaces_the_previous_snapshot(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    await setup.writer.write()
    setup.clock.advance(minutes=1)
    setup.state = "stopped"
    await setup.writer.write()

    data = json.loads((tmp_path / STATUS_FILE).read_text("utf-8"))
    assert data["service"] == "stopped"
    assert data["updated_at"] == "2026-10-29T12:01:00Z"


async def test_write_failure_keeps_the_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = Setup(tmp_path)
    await setup.writer.write()
    before = (tmp_path / STATUS_FILE).read_bytes()

    def fail(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", fail)
    setup.state = "other"

    with pytest.raises(OSError, match="disk full"):
        await setup.writer.write()

    assert (tmp_path / STATUS_FILE).read_bytes() == before
    assert not tmp_leftovers(tmp_path)


async def test_run_writes_every_minute_and_survives_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = Setup(tmp_path)
    attempts = 0
    real_write = setup.writer.write

    async def flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("locked")
        await real_write()

    monkeypatch.setattr(setup.writer, "write", flaky)

    def stop_after_three(_seconds: float) -> None:
        if len(setup.clock.sleeps) >= 3:
            raise asyncio.CancelledError

    setup.clock.on_sleep = stop_after_three
    with pytest.raises(asyncio.CancelledError):
        await setup.writer.run()

    assert attempts == 3
    assert setup.clock.sleeps == [status_module.INTERVAL_SECONDS] * 3
    assert (tmp_path / STATUS_FILE).exists()


@pytest.mark.parametrize(("count", "noun"), [(0, "chats"), (1, "chat"), (2, "chats"), (8, "chats")])
def test_summary_line_pluralises_chats(count: int, noun: str) -> None:
    data: dict[str, Any] = {
        "service": "running",
        "chats": [{}] * count,
        "total_bytes": 0,
        "disk": {"free_gb": 41},
    }

    assert format_status_lines(data)[0].startswith(f"{count} {noun} ")


def test_summary_line_matches_the_tray_example() -> None:
    data: dict[str, Any] = {
        "service": "running",
        "chats": [{}] * 8,
        "total_bytes": int(2.1 * GB),
        "disk": {"free_gb": 41.0},
    }

    assert format_status_lines(data) == ["8 chats · live · 2.1 GB · 41 GB free"]


@pytest.mark.parametrize("service", ["stopped", "starting", "stopping", "paused"])
def test_service_state_other_than_running_is_shown_verbatim(service: str) -> None:
    data: dict[str, Any] = {"service": service, "chats": [], "total_bytes": 0, "disk": {}}

    assert f"· {service} ·" in format_status_lines(data)[0]


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (0, "0.0 GB"),
        (GB // 2, "0.5 GB"),
        (GB // 20 - 1, "0.0 GB"),
        (GB - 1, "1.0 GB"),
        (GB, "1.0 GB"),
        (1536 * 1024**2, "1.5 GB"),
        (10 * GB, "10.0 GB"),
    ],
)
def test_total_size_is_shown_in_gib_with_one_decimal(total: int, expected: str) -> None:
    data: dict[str, Any] = {"service": "running", "chats": [], "total_bytes": total, "disk": {}}

    assert f"· {expected} ·" in format_status_lines(data)[0]


def test_missing_keys_fall_back_to_safe_defaults() -> None:
    assert format_status_lines({}) == ["0 chats · unknown · 0.0 GB · 0 GB free"]


def test_error_lines_follow_the_summary_in_order() -> None:
    data: dict[str, Any] = {
        "service": "running",
        "chats": [],
        "total_bytes": 0,
        "disk": {"free_gb": 3.5},
        "errors": [
            {"source": "library", "message": "bad toml"},
            {"source": "worker-1", "message": "RuntimeError: x"},
        ],
    }

    lines = format_status_lines(data)

    assert lines[1:] == ["error [library]: bad toml", "error [worker-1]: RuntimeError: x"]
    assert "3.5 GB free" in lines[0]


def test_status_snapshot_survives_a_json_round_trip_into_the_formatter(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.registry.add(StubController(1))
    setup.writer.add_error("library", "bad")

    data = json.loads(json.dumps(setup.writer.build(0)))

    assert format_status_lines(data) == [
        "1 chat · live · 0.0 GB · 41 GB free",
        "error [library]: bad",
    ]


def test_now_is_used_for_updated_at(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.clock.advance(seconds=5)

    assert setup.writer.build(0)["updated_at"] == "2026-10-29T12:00:05Z"


class _Entry:
    def __init__(self, name: str, size: int | OSError, path: str = "p") -> None:
        self.name = name
        self.path = path
        self._size = size

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return False

    def stat(self, *, follow_symlinks: bool = True) -> Any:
        if isinstance(self._size, OSError):
            raise self._size
        return SimpleNamespace(st_size=self._size)


class _Scan:
    def __init__(self, entries: list[_Entry]) -> None:
        self._entries = entries

    def __enter__(self) -> list[_Entry]:
        return self._entries

    def __exit__(self, *exc: object) -> None:
        return None


def test_a_file_that_vanishes_during_the_walk_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [
        _Entry("a.jsonl", 10),
        _Entry("gone.jsonl", PermissionError("locked")),
        _Entry("b.jsonl", 5),
    ]

    def scandir(_path: str) -> _Scan:
        return _Scan(entries)

    monkeypatch.setattr(status_module, "os", SimpleNamespace(scandir=scandir))

    assert Setup(tmp_path).writer.build()["total_bytes"] == 15
