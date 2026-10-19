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


def _truth(spec: gen.ChatSpec) -> dict[str, dict[str, Any]]:
    data: dict[str, Any] = json.loads(
        (gen.FIXTURES / gen.TRUTH_DIR / spec.file).read_text(encoding="utf-8")
    )
    assert data["chat_id"] == f"-100{spec.id}"
    return {row["msg_id"]: row for row in data["rows"]}


def _export(spec: gen.ChatSpec) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads((gen.FIXTURES / spec.file).read_text(encoding="utf-8"))
    return data["messages"]


def _plain(message: dict[str, Any]) -> str:
    return "".join(entity["text"] for entity in message["text_entities"])


def _bank_texts(group: str) -> set[str]:
    bank: dict[str, Any] = json.loads(gen.PHRASEBANK.read_text(encoding="utf-8"))
    return {text for texts in bank[group].values() for text in texts}


@pytest.mark.parametrize("spec", gen.CHATS, ids=lambda s: s.file)
def test_truth_has_one_row_per_message(spec: gen.ChatSpec) -> None:
    truth = _truth(spec)
    messages = _export(spec)

    assert list(truth) == [str(m["id"]) for m in messages]
    assert {r["reason"] for r in truth.values() if r["is_noise"]} <= {
        "service", "sticker", "emoji_only", "gratitude", "short", "spam", "duplicate",
    }  # fmt: skip
    assert all(r["reason"] is None for r in truth.values() if not r["is_noise"])
    assert all(r["lang"] in {None, "ru", "es", "en"} for r in truth.values())


@pytest.mark.parametrize("spec", gen.CHATS, ids=lambda s: s.file)
def test_truth_reflects_what_the_generator_meant(spec: gen.ChatSpec) -> None:
    truth = _truth(spec)
    emoji = set(json.loads(gen.PHRASEBANK.read_text(encoding="utf-8"))["emoji_only"])
    gratitude = _bank_texts("gratitude")
    offtopic = {t for t in _bank_texts("offtopic") if "{" not in t}
    seen: dict[str, Any] = {}

    for message in _export(spec):
        row = truth[str(message["id"])]
        text = _plain(message)
        media = message.get("media_type")
        if message["type"] == "service":
            assert (row["is_noise"], row["reason"], row["lang"]) == (True, "service", None)
        elif media == "sticker":
            assert (row["is_noise"], row["reason"]) == (True, "sticker")
        elif text in emoji:
            assert (row["is_noise"], row["reason"]) == (True, "emoji_only")
        elif not text:  # voice, video note, animation, photo without caption
            assert (row["is_noise"], row["lang"]) == (False, None)
        elif text in gratitude:
            assert (row["is_noise"], row["reason"], row["is_question"]) == (
                True,
                "gratitude",
                False,
            )
        elif text in offtopic:
            assert row["is_noise"] is False  # the known gap: the truth does not pretend
        if row["reason"] == "duplicate":
            assert text in seen
            assert row["is_question"] is True
        seen.setdefault(text, message)


@pytest.mark.parametrize("spec", gen.CHATS, ids=lambda s: s.file)
def test_short_replies_are_noise_only_when_they_answer_no_question(spec: gen.ChatSpec) -> None:
    truth = _truth(spec)
    messages = {m["id"]: m for m in _export(spec)}
    short = _bank_texts("short")
    checked = Counter[bool]()

    for message in messages.values():
        target_id = message.get("reply_to_message_id")
        if target_id is None or _plain(message) not in short or "photo" in message:
            continue
        row = truth[str(message["id"])]
        answers_question = truth[str(target_id)]["is_question"] or "?" in _plain(message)
        assert row["is_noise"] is not answers_question
        assert row["reason"] == (None if answers_question else "short")
        checked[answers_question] += 1

    assert checked[True] > 0
    assert checked[False] > 0


def test_truth_counts_per_reason_are_stable() -> None:
    counts = Counter(
        row["reason"] for spec in gen.CHATS for row in _truth(spec).values() if row["is_noise"]
    )

    assert set(counts) == {
        "service", "sticker", "emoji_only", "gratitude", "short", "spam", "duplicate",
    }  # fmt: skip
    assert all(count >= 4 for count in counts.values())
