from __future__ import annotations

from typing import Any

import pytest

from chatradar.pipeline.enrich import EnrichStage, features
from chatradar.pipeline.features import detect_language, is_emoji_only
from tests.unit.pipeline.cases import load_cases
from tests.unit.pipeline.fakes import make_deps, make_message


@pytest.mark.parametrize("case", load_cases("enrich_cases.json"))
def test_features(case: dict[str, Any]) -> None:
    values = features(make_message(1, case["text"], is_noise=False))
    for column in ("lang", "is_question", "urls", "has_mention"):
        if column in case:
            assert values[column] == case[column], column


def test_noise_messages_get_empty_features() -> None:
    values = features(make_message(1, "Where is the consulate? https://example.com", is_noise=True))
    assert values == {"lang": None, "is_question": None, "urls": [], "has_mention": None}


def test_language_ignores_links_and_mentions_when_measuring_length() -> None:
    assert detect_language("@example_admin https://example.com/a/b/c hola") == "unknown"


def test_plain_text_is_not_emoji() -> None:
    assert not is_emoji_only("")
    assert not is_emoji_only("ok!")


async def test_stage_waits_for_noise_and_marks_noise_messages_too() -> None:
    deps, repo, _ = make_deps(
        [
            make_message(1, "Where can I renew my residence card", versions={"noise": 1}),
            make_message(2, "+", is_noise=True, noise_reason="gratitude", versions={"noise": 1}),
            make_message(3, "Not classified yet, so enrich must skip it"),
        ]
    )
    stage = EnrichStage()

    assert await stage.run(deps, limit=100) == 2
    assert await stage.run(deps, limit=100) == 0
    assert repo.row(1).lang == "en"
    assert repo.row(1).is_question is True
    assert repo.row(2).lang is None
    assert repo.row(2).versions == {"noise": 1, "enrich": 1}
    assert repo.row(3).versions == {}
