from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from chatradar.domain.models import MediaType
from chatradar.pipeline.noise import (
    NOISE_VERSION,
    REASON_DUPLICATE,
    REASON_EMOJI_ONLY,
    REASON_GRATITUDE,
    REASON_SERVICE,
    REASON_SHORT,
    REASON_SPAM,
    REASON_STICKER,
    RULES,
    NoiseContext,
    NoiseStage,
    classify,
    fingerprint_index,
)
from tests.unit.pipeline.cases import load_cases
from tests.unit.pipeline.fakes import make_deps, make_message


def _context(case: dict[str, Any]) -> NoiseContext:
    target = None
    if "reply_to_text" in case:
        target = make_message(1, case["reply_to_text"], minutes=-5)
    history = [
        make_message(
            10 + i,
            row["text"],
            minutes=-row["days_before"] * 24 * 60,
            media=MediaType(case.get("media", "none")),
        )
        for i, row in enumerate(case.get("history", []))
    ]
    return NoiseContext(reply_target=target, history=fingerprint_index(history))


@pytest.mark.parametrize("case", load_cases("noise_cases.json"))
def test_noise_rules(case: dict[str, Any]) -> None:
    msg = make_message(
        100,
        case["text"],
        reply_to=1 if "reply_to_text" in case else None,
        media=MediaType(case.get("media", "none")),
        service=case.get("service", False),
    )
    assert classify(msg, _context(case)) == case["expected"]


def test_rules_run_in_the_documented_order() -> None:
    assert [rule.__name__ for rule in RULES] == [
        "service_message",
        "sticker_or_emoji_only",
        "gratitude",
        "short_without_value",
        "spam_patterns",
        "duplicate",
    ]


def test_reasons_are_stable_strings() -> None:
    reasons = [
        REASON_SERVICE,
        REASON_STICKER,
        REASON_EMOJI_ONLY,
        REASON_GRATITUDE,
        REASON_SHORT,
        REASON_DUPLICATE,
        REASON_SPAM,
    ]
    assert reasons == [
        "service",
        "sticker",
        "emoji_only",
        "gratitude",
        "short",
        "duplicate",
        "spam",
    ]


async def test_stage_marks_noise_and_uses_reply_targets_and_history() -> None:
    text = "Selling a used bicycle in good condition, ask me"
    deps, repo, _ = make_deps(
        [
            make_message(1, "Is the market open on Sunday?", minutes=0),
            make_message(2, "yes", minutes=1, reply_to=1),
            make_message(3, "yes", minutes=2),
            make_message(4, text, minutes=3),
            make_message(5, text, minutes=60 * 24 * 5),
            make_message(6, "", minutes=61 * 24 * 5, media=MediaType.VOICE),
        ]
    )
    stage = NoiseStage()

    assert await stage.run(deps, limit=100) == 6
    assert await stage.run(deps, limit=100) == 0

    reasons = {m.msg_id: (m.is_noise, m.noise_reason) for m in repo.rows.values()}
    assert reasons == {
        "1": (False, None),
        "2": (False, None),
        "3": (True, "short"),
        "4": (False, None),
        "5": (True, "duplicate"),
        "6": (False, None),
    }
    assert all(m.versions == {"noise": NOISE_VERSION} for m in repo.rows.values())


async def test_stage_sees_duplicates_from_earlier_processed_batches() -> None:
    text = "Looking for a room near the university from November"
    deps, repo, _ = make_deps([make_message(1, text, minutes=0)])
    stage = NoiseStage()
    await stage.run(deps, limit=100)
    repo.add(make_message(2, text, minutes=60))

    assert await stage.run(deps, limit=100) == 1
    assert repo.row(2).noise_reason == "duplicate"
    assert repo.window_calls[-1][1] == repo.row(2).date - timedelta(days=30)


async def test_stage_respects_the_limit() -> None:
    deps, repo, _ = make_deps([make_message(i, "ok", minutes=i) for i in range(1, 6)])
    stage = NoiseStage()

    assert await stage.run(deps, limit=2) == 2
    assert sum(1 for m in repo.rows.values() if "noise" in m.versions) == 2


async def test_short_replies_that_repeat_naturally_are_not_duplicates() -> None:
    """Regression: on realistic data "why?" and "yes" repeat across a chat every day; the
    duplicate rule flagged answers that the short rule deliberately keeps."""
    deps, repo, _ = make_deps(
        [
            make_message(1, "Is the market open on Sunday?", minutes=0),
            make_message(2, "yes", minutes=1, reply_to=1),
            make_message(3, "Does the bank open on Saturday?", minutes=60),
            make_message(4, "yes", minutes=61, reply_to=3),
            make_message(5, "why?", minutes=62, reply_to=4),
            make_message(6, "why?", minutes=63, reply_to=2),
        ]
    )
    await NoiseStage().run(deps, limit=100)

    assert {m.msg_id: m.noise_reason for m in repo.rows.values()} == dict.fromkeys(
        ("1", "2", "3", "4", "5", "6")
    )
