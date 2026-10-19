from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from chatradar.config import LearningSettings
from chatradar.domain.evaluation import MessageLabel
from chatradar.domain.lexicon import LexiconKind, LexiconTerm
from chatradar.domain.models import MediaType, StoredMessage
from chatradar.learning.corpus import CorpusMiner
from chatradar.learning.text import is_safe_term
from tests.unit.learning.fakes import CHAT, NOW, make_message

SETTINGS = LearningSettings(min_occurrences=3, min_authors=3, min_chats=1, min_score=1.0)

FILLER = (
    "where can i file the documents downtown",
    "how much is a flat near the central market",
    "which bank is best for newcomers opening an account",
    "the notary office near the plaza opens at nine",
    "need a certificate for school, who to ask",
    "sending money from abroad without fees",
    "a good paediatrician for a small child",
    "is the shop open on sundays in the evening",
)


def background(count: int, *, start: int = 1000) -> list[StoredMessage]:
    """Ordinary thread-starting messages by many authors."""
    return [
        make_message(
            start + i,
            f"{FILLER[i % len(FILLER)]} number {i}",
            author=f"bg{i % 25}",
            thread_id=f"{CHAT}:{start + i}",
            is_noise=False,
        )
        for i in range(count)
    ]


def mine(
    messages: list[StoredMessage], labels: list[MessageLabel] | None = None
) -> list[LexiconTerm]:
    miner = CorpusMiner(SETTINGS, {label.key: label for label in labels or []})
    for msg in messages:
        miner.observe(msg)
    return miner.terms()


def terms_of(found: list[LexiconTerm], kind: LexiconKind) -> set[str]:
    return {t.term for t in found if t.kind is kind}


def gratitude_replies(text: str, authors: int, start: int = 1, **extra: Any) -> list[StoredMessage]:
    return [
        make_message(start + i, text, author=f"th{i}", reply_to=str(1000 + i), **extra)
        for i in range(authors)
    ]


def spam_messages(text: str, authors: int, start: int = 5000) -> list[StoredMessage]:
    return [
        make_message(
            start + i, text, author=f"sp{i}", is_noise=True, noise_reason="spam", lang="en"
        )
        for i in range(authors)
    ]


def test_gratitude_needs_several_authors_and_a_thread_starter_background() -> None:
    corpus = [
        *background(200),
        *gratitude_replies("Thanks a lot!", 6),
        *[
            make_message(300 + i, "hooray hooray", author="solo", reply_to="1000")
            for i in range(200)
        ],
    ]

    found = mine(corpus)

    assert terms_of(found, LexiconKind.GRATITUDE) == {"thanks a lot"}
    [term] = [t for t in found if t.kind is LexiconKind.GRATITUDE]
    assert (term.occurrences, term.authors, term.chats) == (6, 6, 1)
    assert term.score >= SETTINGS.min_score
    assert len(term.examples) == SETTINGS.max_examples
    assert term.examples[0].chat_id == CHAT


def test_gratitude_skips_questions_media_long_text_links_and_service() -> None:
    skipped = [
        *gratitude_replies("thanks?", 5, start=10),
        *gratitude_replies("look", 5, start=20, media=MediaType.PHOTO),
        *gratitude_replies("once more a huge thank you for everything you did", 5, start=30),
        *gratitude_replies("a b c d e f g", 5, start=40),
        *gratitude_replies("look t.me/chat", 5, start=50),
        *gratitude_replies("joined", 5, start=60, is_service=True),
        *gratitude_replies("thanks @bob", 5, start=70),
    ]

    assert terms_of(mine([*background(200), *skipped]), LexiconKind.GRATITUDE) == set()


def test_gratitude_without_thread_starters_proposes_nothing() -> None:
    assert mine(gratitude_replies("thanks", 8)) == []


def test_a_phrase_that_opens_threads_is_not_gratitude() -> None:
    openers = [
        make_message(2000 + i, "good day", author=f"op{i}", thread_id=f"{CHAT}:{2000 + i}")
        for i in range(300)
    ]
    corpus = [*background(10), *openers, *gratitude_replies("good day", 6)]

    assert "good day" not in terms_of(mine(corpus), LexiconKind.GRATITUDE)


def test_spam_ngrams_split_into_offers_and_contacts() -> None:
    corpus = [
        *background(300),
        *spam_messages("Earn five hundred weekly, write me in DM @easy_demo", 8),
    ]

    found = mine(corpus)

    offers = terms_of(found, LexiconKind.SPAM_OFFERS)
    contacts = terms_of(found, LexiconKind.SPAM_CONTACTS)
    assert "earn" in offers
    assert "earn five hundred" in offers
    assert "me in dm" in contacts
    assert "dm" in contacts
    assert offers.isdisjoint(contacts)
    assert all(is_safe_term(t) and "easy" not in t for t in offers | contacts)
    assert all(t.lang == "en" for t in found if t.kind is LexiconKind.SPAM_OFFERS)


def test_one_spammer_with_200_copies_does_not_pass_min_authors() -> None:
    copies = [
        make_message(
            6000 + i,
            "earn without investment write me in dm",
            author="spammer",
            is_noise=True,
            noise_reason="spam",
        )
        for i in range(200)
    ]

    assert mine([*background(300), *copies]) == []


def test_spam_candidates_respect_min_occurrences() -> None:
    corpus = [*background(300), *spam_messages("earn without investment", 2)]

    assert mine(corpus) == []


def test_privacy_guards_drop_handles_links_and_phone_numbers() -> None:
    text = "sale write @promo_demo https://shop.example/x call 099123456 today"
    found = mine([*background(300), *spam_messages(text, 8)])

    every = {t.term for t in found}
    assert "sale" in every
    assert "today" in every
    assert not any("promo" in t or "shop" in t or "099" in t or "http" in t for t in every)
    assert "sale write" in every
    assert not any(t.startswith("write call") or "write today" in t for t in every)


def test_question_phrases_use_the_leading_words_of_questions() -> None:
    questions = [
        make_message(7000 + i, f"Who knows how to handle {FILLER[i % 8]}?", author=f"q{i}")
        for i in range(10)
    ]
    statements = [
        make_message(8000 + i, f"{FILLER[i % 8]} just so", author=f"s{i % 20}") for i in range(200)
    ]

    found = mine([*questions, *statements])

    assert {"who knows", "who knows how"} <= terms_of(found, LexiconKind.QUESTION_PHRASES)


def test_question_phrases_ignore_mention_led_messages() -> None:
    questions = [
        make_message(7000 + i, f"@bob{i}abc who knows?", author=f"q{i}") for i in range(10)
    ]

    assert mine([*questions, *background(100)]) == []


def test_dominant_language_or_any() -> None:
    russian = [
        make_message(
            9000 + i,
            "Earn money write me in dm",
            author=f"a{i}",
            is_noise=True,
            noise_reason="spam",
            lang="en",
        )
        for i in range(6)
    ]
    mixed = [
        make_message(
            9100 + i,
            "Ganá plata escribime privado",
            author=f"b{i}",
            is_noise=True,
            noise_reason="spam",
            lang="es" if i % 2 else "en",
        )
        for i in range(6)
    ]

    found = mine([*background(300), *russian, *mixed])

    by_term = {t.term: t.lang for t in found}
    assert by_term["earn"] == "en"
    assert by_term["plata"] == "any"


def label(msg: StoredMessage, *, noise: bool, reason: str | None = None) -> MessageLabel:
    return MessageLabel(
        source=msg.source,
        chat_id=msg.chat_id,
        msg_id=msg.msg_id,
        is_noise=noise,
        reason=reason,
        created_at=NOW,
    )


def test_human_label_overrides_the_filter_verdict() -> None:
    flagged = spam_messages("course ads now", 8, start=100)
    unflagged = [
        make_message(200 + i, "course ads now", author=f"u{i}", is_noise=False) for i in range(8)
    ]
    labels = [
        *(label(m, noise=False) for m in flagged),
        *(label(m, noise=True, reason="spam") for m in unflagged),
    ]

    without_labels = mine([*background(300), *flagged, *unflagged])
    with_labels = mine([*background(300), *flagged, *unflagged], labels)

    assert "ads" in terms_of(without_labels, LexiconKind.SPAM_OFFERS)
    assert {t.occurrences for t in with_labels if t.term == "ads"} == {8}
    assert all(
        {e.msg_id for e in t.examples} <= {m.msg_id for m in unflagged}
        for t in with_labels
        if t.term == "ads"
    )


def test_human_noise_label_with_another_reason_is_not_spam() -> None:
    flagged = spam_messages("course ads now", 8, start=100)
    labels = [label(m, noise=True, reason="short") for m in flagged]

    found = mine([*background(300), *flagged], labels)

    assert terms_of(found, LexiconKind.SPAM_OFFERS) == set()
    assert terms_of(found, LexiconKind.SPAM_CONTACTS) == set()


def test_candidates_are_capped_per_kind_best_first() -> None:
    settings = SETTINGS.model_copy(update={"max_candidates_per_kind": 2})
    miner = CorpusMiner(settings)
    for msg in [
        *background(300),
        *spam_messages("earn money by writing quickly to everyone you know today", 8),
    ]:
        miner.observe(msg)

    terms = miner.terms()

    offers = [t for t in terms if t.kind is LexiconKind.SPAM_OFFERS]
    assert len(offers) == 2
    assert offers == sorted(offers, key=lambda t: -t.score)


def test_first_and_last_seen_come_from_message_dates() -> None:
    old = make_message(
        1, "course ads now", author="a", days_ago=40, is_noise=True, noise_reason="spam"
    )
    recent = [
        make_message(
            2 + i, "course ads now", author=f"b{i}", days_ago=2, is_noise=True, noise_reason="spam"
        )
        for i in range(6)
    ]

    [term] = [
        t
        for t in mine([*background(300), old, *recent])
        if t.term == "course ads now" and t.kind is LexiconKind.SPAM_OFFERS
    ]

    assert term.first_seen == NOW - timedelta(days=40)
    assert term.last_seen == NOW - timedelta(days=2)


@pytest.mark.parametrize("max_ngram", [1, 2])
def test_max_ngram_limits_the_order(max_ngram: int) -> None:
    settings = SETTINGS.model_copy(update={"max_ngram": max_ngram})
    miner = CorpusMiner(settings)
    for msg in [*background(300), *spam_messages("earn write quickly", 8)]:
        miner.observe(msg)

    spam = [t for t in miner.terms() if t.kind is LexiconKind.SPAM_OFFERS]
    assert spam
    assert {len(t.term.split()) for t in spam} <= set(range(1, max_ngram + 1))
