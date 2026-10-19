"""The three candidate generators. Each sees every message once and then yields terms.

- `GratitudeMiner` — whole short messages repeated by several authors. The target class is
  the short messages that do not start a thread, the background is the messages that do
  (nobody opens a discussion with "thanks!").
- `SpamMiner`      — n-grams of spam messages against all other messages; one containing a
  contact word is `spam_contacts`, the rest `spam_offers`.
- `QuestionMiner`  — the leading 2-3 words of questions against the leading words of others.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Protocol

from chatradar.domain.lexicon import LexiconKind, LexiconTerm
from chatradar.domain.models import MediaType
from chatradar.learning.contact_words import has_contact_word
from chatradar.learning.tally import Tally, to_candidate
from chatradar.learning.text import (
    is_safe_term,
    is_unsafe_text,
    leading_tokens,
    message_ngrams,
)
from chatradar.pipeline.lexicons import fold

if TYPE_CHECKING:
    from collections.abc import Iterable

    from chatradar.config import LearningSettings
    from chatradar.domain.models import StoredMessage
    from chatradar.learning.verdict import Verdict

GRATITUDE_MAX_TOKENS = 6
GRATITUDE_MAX_CHARS = 40
QUESTION_ORDERS = (2, 3)


class Miner(Protocol):
    def observe(self, msg: StoredMessage, verdict: Verdict) -> None: ...

    def candidates(self) -> list[LexiconTerm]: ...


def _by_order(terms: Iterable[str]) -> dict[int, list[str]]:
    grouped: defaultdict[int, list[str]] = defaultdict(list)
    for term in terms:
        grouped[term.count(" ") + 1].append(term)
    return grouped


class GratitudeMiner:
    def __init__(self, settings: LearningSettings) -> None:
        self._settings = settings
        self._tally = Tally(settings.max_examples)

    def observe(self, msg: StoredMessage, verdict: Verdict) -> None:
        folded = fold(msg.text)
        if not folded:
            return
        short = self._is_short_message(msg, folded, verdict)
        if msg.thread_id == f"{msg.chat_id}:{msg.msg_id}":
            self._tally.count_background()
            if short:
                self._tally.note_background(folded)
        elif short:
            self._tally.add_target([folded], msg)

    @staticmethod
    def _is_short_message(msg: StoredMessage, folded: str, verdict: Verdict) -> bool:
        text = msg.text.strip()
        return (
            bool(folded)
            and len(text) <= GRATITUDE_MAX_CHARS
            and len(folded.split()) <= GRATITUDE_MAX_TOKENS
            and "?" not in text
            and msg.media_type is MediaType.NONE
            and not msg.is_service
            and not verdict.human_useful
            and not is_unsafe_text(text)
            and is_safe_term(folded)
        )

    def candidates(self) -> list[LexiconTerm]:
        if not self._tally.has_background:
            return []
        return [to_candidate(LexiconKind.GRATITUDE, s) for s in self._tally.passing(self._settings)]


class SpamMiner:
    def __init__(self, settings: LearningSettings) -> None:
        self._settings = settings
        self._tally = Tally(settings.max_examples)

    def observe(self, msg: StoredMessage, verdict: Verdict) -> None:
        if not msg.text:
            return
        for order, terms in _by_order(message_ngrams(msg.text, self._settings.max_ngram)).items():
            if verdict.is_spam:
                self._tally.add_target(terms, msg, order)
            else:
                self._tally.add_background(terms, order)

    def candidates(self) -> list[LexiconTerm]:
        return [
            to_candidate(
                LexiconKind.SPAM_CONTACTS if has_contact_word(s.term) else LexiconKind.SPAM_OFFERS,
                s,
            )
            for s in self._tally.passing(self._settings)
        ]


class QuestionMiner:
    def __init__(self, settings: LearningSettings) -> None:
        self._settings = settings
        self._tally = Tally(settings.max_examples)

    def observe(self, msg: StoredMessage, verdict: Verdict) -> None:
        orders = [n for n in QUESTION_ORDERS if n <= self._settings.max_ngram]
        if not orders:
            return
        tokens = leading_tokens(msg.text)
        leading = {
            order: [phrase]
            for order in orders
            if len(tokens) >= order and is_safe_term(phrase := " ".join(tokens[:order]))
        }
        for order, grouped in leading.items():
            if verdict.is_question:
                self._tally.add_target(grouped, msg, order)
            else:
                self._tally.add_background(grouped, order)

    def candidates(self) -> list[LexiconTerm]:
        return [
            to_candidate(LexiconKind.QUESTION_PHRASES, s)
            for s in self._tally.passing(self._settings)
        ]
