from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from chatradar.connectors.tg_export.mapper import map_record
from chatradar.connectors.tg_export.parser import parse_export
from scripts import generate_synthetic as gen

if TYPE_CHECKING:
    from pathlib import Path

FETCHED = datetime(2026, 10, 19, tzinfo=UTC)


def test_generation_is_deterministic() -> None:
    assert gen.render_all() == gen.render_all()
    assert gen.render_all(seed=1) != gen.render_all()


def test_committed_fixtures_are_in_sync() -> None:
    assert gen.main(["--check"]) == 0


def test_check_fails_on_stale_files(tmp_path: Path) -> None:
    assert gen.main(["--out", str(tmp_path)]) == 0
    (tmp_path / gen.CHATS[0].file).write_text("{}", encoding="utf-8")

    assert gen.main(["--check", "--out", str(tmp_path)]) == 1


@pytest.mark.parametrize("spec", gen.CHATS, ids=lambda s: s.file)
def test_every_message_parses_and_maps(spec: gen.ChatSpec) -> None:
    [(chat, records)] = parse_export(gen.FIXTURES / spec.file, fetched_at=FETCHED)

    messages = [map_record(record, chat) for record in records]

    assert chat.chat_id == f"-100{spec.id}"
    assert all(m is not None for m in messages)
    ids = [int(r.payload["id"]) for r in records]
    assert ids == sorted(ids) == list(range(1, len(ids) + 1))
    dates = [m.date for m in messages if m is not None]
    assert dates == sorted(dates)


@pytest.mark.parametrize("spec", gen.CHATS, ids=lambda s: s.file)
def test_shape_matches_real_chat_statistics(spec: gen.ChatSpec) -> None:
    """Rates measured on real exports (aggregates only); wide bounds, the point is realism."""
    data: dict[str, Any] = json.loads((gen.FIXTURES / spec.file).read_text(encoding="utf-8"))
    messages = [m for m in data["messages"] if m["type"] == "message"]
    counts = Counter(
        key
        for m in messages
        for key, present in (
            ("reply", "reply_to_message_id" in m),
            ("edited", "edited" in m),
            ("forward", "forwarded_from" in m),
            ("media", "photo" in m or "media_type" in m),
        )
        if present
    )
    n = len(messages)

    assert 250 <= n <= 800
    assert 0.5 <= counts["reply"] / n <= 0.8
    assert 0.15 <= counts["edited"] / n <= 0.35
    assert 0.03 <= counts["media"] / n <= 0.2
    assert any(m["type"] == "service" for m in data["messages"])
    reply_ids = {m["reply_to_message_id"] for m in messages if "reply_to_message_id" in m}
    assert reply_ids <= {m["id"] for m in data["messages"]}


def test_all_three_languages_are_present() -> None:
    names = {spec.file.split("_")[0] for spec in gen.CHATS}
    langs = {lang for spec in gen.CHATS for lang in spec.langs}

    assert names >= {"ru", "es", "en"}
    assert langs == {"ru", "es", "en"}
