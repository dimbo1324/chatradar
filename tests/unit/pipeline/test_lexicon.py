from __future__ import annotations

from pathlib import Path

import pytest

from chatradar.domain.lexicon import LexiconKind, LexiconSnapshot, TermSource, TermStatus
from chatradar.pipeline.enrich import features
from chatradar.pipeline.features import looks_like_question
from chatradar.pipeline.lexicon import Lexicon, load_lexicon, seed_terms
from chatradar.pipeline.lexicons import fold
from chatradar.pipeline.noise import NoiseContext, classify
from tests.unit.pipeline.fakes import make_message

LEXICON_DIR = Path(__file__).parents[3] / "src" / "chatradar" / "resources" / "lexicons"


def _file_entries(kind: LexiconKind) -> set[str]:
    lines = (LEXICON_DIR / f"{kind.value}.txt").read_text(encoding="utf-8").splitlines()
    return {s for line in lines if (s := line.strip()) and not s.startswith("#")}


def _custom(**entries: tuple[str, ...]) -> Lexicon:
    return Lexicon.from_snapshot(LexiconSnapshot(revision=7, entries=entries))


@pytest.mark.parametrize("kind", list(LexiconKind))
def test_seed_lexicon_matches_the_files(kind: LexiconKind) -> None:
    entries = _file_entries(kind)
    lexicon = Lexicon.from_seed()

    assert lexicon.raw(kind) == entries
    assert lexicon.folded(kind) == {f for e in entries if (f := fold(e))}
    assert entries


def test_seed_terms_are_active_seed_terms_with_languages() -> None:
    terms = seed_terms()
    by_key = {t.key: t for t in terms}

    assert len(by_key) == len(terms)
    assert all(t.status is TermStatus.ACTIVE and t.source is TermSource.SEED for t in terms)
    assert {t.lang for t in terms} == {"any", "ru", "es", "en"}
    assert any(t.kind is LexiconKind.GRATITUDE and t.lang == "ru" for t in terms)
    assert by_key[(LexiconKind.GRATITUDE, "es", "gracias")].lang == "es"
    assert by_key[(LexiconKind.GRATITUDE, "en", "thanks")].lang == "en"


def test_symbol_entries_before_a_language_marker_are_language_free() -> None:
    by_key = {t.key: t for t in seed_terms()}

    assert (LexiconKind.GRATITUDE, "any", "+1") in by_key


def test_folded_forms_drop_case_accents_and_punctuation() -> None:
    lexicon = _custom(gratitude=("Gracias", "+1", "Bendición"))

    assert lexicon.raw(LexiconKind.GRATITUDE) == {"Gracias", "+1", "Bendición"}
    assert lexicon.folded(LexiconKind.GRATITUDE) == {"gracias", "1", "bendicion"}
    assert lexicon.revision == 7
    assert lexicon.raw(LexiconKind.QUESTIONS) == frozenset()


async def test_load_lexicon_without_a_repository_is_the_seed() -> None:
    assert await load_lexicon(None) is Lexicon.from_seed()


def test_accepted_term_changes_the_verdict() -> None:
    msg = make_message(1, "Good morning all everyone")
    seed = NoiseContext()
    custom = NoiseContext(lexicon=_custom(gratitude=("good morning all everyone",)))

    assert classify(msg, seed) is None
    assert classify(msg, custom) == "gratitude"


def test_rejected_seed_term_stops_matching() -> None:
    msg = make_message(1, "Thanks for sharing")
    without = _custom(gratitude=("thanks",))

    assert classify(msg, NoiseContext()) == "gratitude"
    assert classify(msg, NoiseContext(lexicon=without)) is None


def test_spam_needs_offer_and_contact_from_the_lexicon() -> None:
    msg = make_message(1, "quick riches, knock me")
    lexicon = _custom(spam_offers=("quick riches",), spam_contacts=("knock me",))

    assert classify(msg, NoiseContext()) != "spam"
    assert classify(msg, NoiseContext(lexicon=lexicon)) == "spam"
    only_offer = _custom(spam_offers=("quick riches",))
    assert classify(msg, NoiseContext(lexicon=only_offer)) != "spam"


def test_question_words_come_from_the_lexicon() -> None:
    text = "whereabouts is the office"
    custom = _custom(questions=("whereabouts",))

    assert not looks_like_question(text)
    assert looks_like_question(text, custom)
    assert looks_like_question("anything? yes")
    assert not looks_like_question("who knows", _custom())


def test_enrich_features_use_the_given_lexicon() -> None:
    msg = make_message(1, "kindly advise on the permit")
    custom = _custom(question_phrases=("kindly advise",))

    assert features(msg)["is_question"] is False
    assert features(msg, custom)["is_question"] is True
