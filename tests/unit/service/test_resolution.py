"""The resolution book: shared chats, retries, errors and masked invite links (A3, S13)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from chatimport.library import ChatEntry, parse_library
from chatimport.ports import ResolvedChat, ResolveStatus
from chatimport.resolution import (
    ActiveChats,
    ErrorBook,
    ResolvedEntry,
    display_ref,
    resolve_error_key,
)
from tests.unit.service.harness import library_text, make_env

if TYPE_CHECKING:
    from pathlib import Path

A, B = -1001, -1002


def found(entry: ChatEntry, chat_id: int) -> ResolvedEntry:
    return ResolvedEntry(entry, ResolvedChat(entry.key, ResolveStatus.FOUND, chat_id=chat_id))


def missing(entry: ChatEntry, status: ResolveStatus = ResolveStatus.NOT_FOUND) -> ResolvedEntry:
    return ResolvedEntry(entry, ResolvedChat(entry.key, status))


class RecordingSink:
    def __init__(self) -> None:
        self.errors: dict[str, str] = {}

    def add_error(self, key: str, text: str) -> None:
        self.errors[key] = text

    def clear_error(self, key: str) -> None:
        self.errors.pop(key, None)


def test_active_book_release_keeps_shared_chat() -> None:
    first, second = ChatEntry("@a"), ChatEntry("https://t.me/a")
    book = ActiveChats(ErrorBook())
    book.absorb([found(first, A), found(second, A)])

    assert book.release(first) is None
    assert len(book) == 1
    assert book.release(second) == A
    assert book.release(second) is None
    assert book.entries() == []


def test_absorb_counts_failures_and_queues_only_retryable_ones() -> None:
    ok, gone, human = ChatEntry("@ok"), ChatEntry("@gone"), ChatEntry("@human")
    book = ActiveChats(ErrorBook())

    absorbed = book.absorb([found(ok, A), missing(gone), missing(human, ResolveStatus.NOT_A_CHAT)])

    assert [item.entry for item in absorbed.found] == [ok]
    assert (absorbed.failed, absorbed.total) == (2, 3)
    assert book.has_unresolved
    library = parse_library(library_text(("@gone", None, True), ("@human", None, True)))
    assert book.retry_candidates(library) == [gone]
    assert not book.has_unresolved


def test_retry_skips_entries_removed_or_disabled_since() -> None:
    gone, off = ChatEntry("@gone"), ChatEntry("@off")
    book = ActiveChats(ErrorBook())
    book.absorb([missing(gone), missing(off)])

    assert book.retry_candidates(parse_library(library_text(("@off", None, False)))) == []


def test_found_entry_clears_its_old_error_and_retry() -> None:
    entry = ChatEntry("@later")
    errors = ErrorBook()
    book = ActiveChats(errors)
    book.absorb([missing(entry)])
    assert resolve_error_key(entry) in errors.items()

    book.absorb([found(entry, B)])

    assert errors.items() == {}
    assert not book.has_unresolved


def test_error_book_replays_into_a_new_sink_and_detaches() -> None:
    errors = ErrorBook()
    errors.set("library", "broken")
    sink = RecordingSink()

    errors.attach(sink)
    errors.set("resolve:@x", "@x: not_found")
    errors.clear("library")
    errors.attach(None)
    errors.set("late", "kept in the book only")

    assert sink.errors == {"resolve:@x": "@x: not_found"}
    assert errors.items() == {"resolve:@x": "@x: not_found", "late": "kept in the book only"}


@pytest.mark.parametrize(
    "ref",
    [
        "https://t.me/+SECRETHASH123",
        "t.me/+SECRETHASH123",
        "https://t.me/joinchat/SECRETHASH123",
        "  https://telegram.me/+SECRETHASH123?x=1 ",
    ],
)
def test_display_ref_masks_invite_hashes(ref: str) -> None:
    shown = display_ref(ref)

    assert "SECRETHASH123" not in shown
    assert shown.startswith("t.me/+SEC...#")


def test_display_ref_tells_two_invites_apart() -> None:
    assert display_ref("t.me/+SECaaaa") != display_ref("t.me/+SECbbbb")


@pytest.mark.parametrize("ref", ["@alpha", "-1001234", "My group", " @alpha "])
def test_display_ref_keeps_public_refs(ref: str) -> None:
    assert display_ref(ref) == ref.strip()


async def test_status_errors_mask_invite_hash(tmp_path: Path) -> None:
    invite = "https://t.me/+SECRETHASH123"
    env = make_env(
        tmp_path,
        library=library_text((invite, None, True), ("@a", "Alpha", True)),
        chats={"@a": (A, "Alpha")},
    )
    env.start()
    await env.wait_live(A)
    data = await env.status()
    await env.stop()

    assert data is not None
    text = json.dumps(data)
    assert "SECRETHASH123" not in text
    assert any(error["source"].startswith("resolve:t.me/+SEC...") for error in data["errors"])
    assert all("SECRETHASH123" not in note.message for note in env.notifier.notes)
