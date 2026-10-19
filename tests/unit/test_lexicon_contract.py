from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from chatradar.config import LearningSettings, Settings
from chatradar.domain.evaluation import MessageLabel
from chatradar.domain.lexicon import (
    NOISE_LEXICON_KINDS,
    QUESTION_LEXICON_KINDS,
    STAGE_LEXICON_KINDS,
    LexiconKind,
    LexiconSnapshot,
    LexiconTerm,
    TermDecision,
    TermStatus,
    changes_active_set,
    next_status,
)
from chatradar.domain.models import Source
from chatradar.pipeline import noise
from chatradar.pipeline.base import STAGE_ORDER, StageDeps
from chatradar.services.feedback import (
    FeedbackServices,
    InvalidLabelError,
    UnknownMessageError,
    UnknownTermError,
)

if TYPE_CHECKING:
    from chatradar.domain.models import MessageKey

KEY = (Source.TELEGRAM, "-100500", "7")


def test_decisions_lead_to_fixed_statuses() -> None:
    assert next_status(TermDecision.ACCEPT) is TermStatus.ACTIVE
    assert next_status(TermDecision.REJECT) is TermStatus.REJECTED
    assert next_status(TermDecision.RESET) is TermStatus.CANDIDATE


@pytest.mark.parametrize(
    ("old", "new", "moves"),
    [
        (TermStatus.CANDIDATE, TermStatus.ACTIVE, True),
        (TermStatus.ACTIVE, TermStatus.REJECTED, True),
        (TermStatus.ACTIVE, TermStatus.CANDIDATE, True),
        (TermStatus.DORMANT, TermStatus.ACTIVE, True),
        (TermStatus.ACTIVE, TermStatus.DORMANT, True),
        (TermStatus.CANDIDATE, TermStatus.REJECTED, False),
        (TermStatus.REJECTED, TermStatus.CANDIDATE, False),
        (TermStatus.ACTIVE, TermStatus.ACTIVE, False),
    ],
)
def test_revision_moves_only_when_the_active_set_changes(
    old: TermStatus, new: TermStatus, moves: bool
) -> None:
    assert changes_active_set(old, new) is moves


def test_stage_kinds_cover_every_kind_exactly_once() -> None:
    kinds = [kind for group in STAGE_LEXICON_KINDS.values() for kind in group]

    assert sorted(kinds) == sorted(LexiconKind)
    assert set(NOISE_LEXICON_KINDS) | set(QUESTION_LEXICON_KINDS) == set(LexiconKind)
    assert set(STAGE_LEXICON_KINDS) <= set(STAGE_ORDER)


def test_seed_file_names_match_the_kinds() -> None:
    from importlib.resources import files

    folder = files("chatradar").joinpath("resources", "lexicons")
    names = {
        item.name.removesuffix(".txt") for item in folder.iterdir() if item.name.endswith(".txt")
    }

    assert names == {kind.value for kind in LexiconKind}


def test_term_key_and_validation() -> None:
    term = LexiconTerm(kind=LexiconKind.GRATITUDE, term="thanks")

    assert term.key == (LexiconKind.GRATITUDE, "any", "thanks")
    assert term.status is TermStatus.CANDIDATE
    with pytest.raises(ValidationError):
        LexiconTerm(kind=LexiconKind.GRATITUDE, term="")
    with pytest.raises(ValidationError):
        LexiconTerm(kind=LexiconKind.GRATITUDE, term="x", weight=-1)


def test_snapshot_returns_terms_by_kind() -> None:
    snapshot = LexiconSnapshot(revision=3, entries={"gratitude": ("thanks", "gracias")})

    assert snapshot.terms(LexiconKind.GRATITUDE) == ("thanks", "gracias")
    assert snapshot.terms(LexiconKind.SPAM_OFFERS) == ()


def test_noise_reasons_are_all_declared_reasons() -> None:
    declared = {v for k, v in vars(noise).items() if k.startswith("REASON_")}

    assert declared == noise.NOISE_REASONS


def test_stage_deps_lexicon_is_optional() -> None:
    deps = StageDeps(messages=object(), search=object())  # type: ignore[arg-type]

    assert deps.lexicon is None


def test_learning_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert LearningSettings().min_authors == 3
    monkeypatch.setenv("CHATRADAR_LEARNING__MIN_OCCURRENCES", "9")
    monkeypatch.setenv("CHATRADAR_LEARNING__MIN_CHATS", "")

    settings = Settings()

    assert settings.learning.min_occurrences == 9
    assert settings.learning.min_chats == 1
    with pytest.raises(ValidationError):
        LearningSettings(min_occurrences=0)


class FakeLexicon:
    def __init__(self, known: set[tuple[str, str, str]]) -> None:
        self.known = known
        self.calls: list[tuple[Any, ...]] = []

    async def decide(
        self,
        kind: LexiconKind,
        lang: str,
        term: str,
        decision: TermDecision,
        *,
        by: str,
        note: str | None,
    ) -> LexiconTerm:
        if (kind.value, lang, term) not in self.known:
            raise KeyError(term)
        self.calls.append((kind, lang, term, decision, by, note))
        return LexiconTerm(
            kind=kind, lang=lang, term=term, status=next_status(decision), decided_by=by, note=note
        )


class FakeLabels:
    def __init__(self) -> None:
        self.saved: list[MessageLabel] = []

    async def save_label(self, label: MessageLabel) -> None:
        self.saved.append(label)


class FakeMessages:
    async def get_many(self, keys: list[MessageKey]) -> dict[MessageKey, object]:
        return {key: object() for key in keys if key == KEY}


def _feedback() -> tuple[FeedbackServices, FakeLexicon, FakeLabels]:
    lexicon = FakeLexicon({("gratitude", "any", "thanks")})
    labels = FakeLabels()
    service = FeedbackServices(
        lexicon=lexicon,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        messages=FakeMessages(),  # type: ignore[arg-type]
    )
    return service, lexicon, labels


async def test_decide_term_records_the_human_and_maps_unknown_terms() -> None:
    service, lexicon, _ = _feedback()

    term = await service.decide_term(
        LexiconKind.GRATITUDE, "any", "thanks", TermDecision.ACCEPT, "ok"
    )

    assert term.status is TermStatus.ACTIVE
    assert lexicon.calls[0][4:] == ("human", "ok")
    with pytest.raises(UnknownTermError):
        await service.decide_term(LexiconKind.GRATITUDE, "any", "nope", TermDecision.ACCEPT)


async def test_label_message_validates_and_saves() -> None:
    service, _, labels = _feedback()

    label = await service.label_message(KEY, is_noise=True, reason="spam")

    assert isinstance(label, MessageLabel)
    assert labels.saved == [label]
    assert label.created_at.tzinfo is not None
    await service.label_message(KEY, is_noise=False, is_question=True)
    assert len(labels.saved) == 2


@pytest.mark.parametrize(
    ("is_noise", "reason", "error"),
    [(False, "spam", InvalidLabelError), (True, "bogus", InvalidLabelError)],
)
async def test_label_message_rejects_contradictions(
    is_noise: bool, reason: str, error: type[Exception]
) -> None:
    service, _, labels = _feedback()

    with pytest.raises(error):
        await service.label_message(KEY, is_noise=is_noise, reason=reason)
    assert labels.saved == []


async def test_label_of_an_unknown_message_is_refused() -> None:
    service, _, labels = _feedback()

    with pytest.raises(UnknownMessageError):
        await service.label_message((Source.TELEGRAM, "-100500", "999"), is_noise=True)
    assert labels.saved == []
