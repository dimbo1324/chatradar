"""Stage `noise`: mark messages that carry no information. Nothing is deleted.

Rules are pure functions `(message, context) -> reason | None`; the first match wins. The
reasons below are stored in `messages.noise_reason` and shown in the panel — they are part
of the data format, so an existing value is never renamed.

- `service`    — a service event ("joined the group", a pinned message).
- `sticker`    — a sticker.
- `emoji_only` — text of emoji only, without media.
- `gratitude`  — only thanks or agreement: "thanks!", "gracias", "+", "+1".
- `short`      — under `SHORT_LIMIT` characters, without media, not a question and not a
                 reply to a question ("yes" after "is there a bus?" stays).
- `spam`       — an easy-money offer together with a link or a write-me-privately phrase.
- `duplicate`  — the same text (`domain.text.fingerprint`) appeared in the same chat within
                 `DUPLICATE_WINDOW` before it; only for texts of at least
                 `DUPLICATE_MIN_CHARS` ("why?" or "yes" repeat naturally).

Voice messages, photos, videos and documents without text are not noise.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from chatradar.domain.models import MediaType, StageResult
from chatradar.domain.text import fingerprint
from chatradar.pipeline.features import (
    ChronoKey,
    chrono_key,
    extract_urls,
    is_emoji_only,
    looks_like_question,
)
from chatradar.pipeline.lexicons import (
    GRATITUDE,
    SPAM_CONTACTS,
    SPAM_OFFERS,
    contains_phrase,
    fold,
    folded_entries,
    raw_entries,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from chatradar.domain.models import MessageKey, Source, StoredMessage
    from chatradar.pipeline.base import StageDeps

REASON_SERVICE = "service"
REASON_STICKER = "sticker"
REASON_EMOJI_ONLY = "emoji_only"
REASON_GRATITUDE = "gratitude"
REASON_SHORT = "short"
REASON_DUPLICATE = "duplicate"
REASON_SPAM = "spam"

SHORT_LIMIT = 15
DUPLICATE_WINDOW = timedelta(days=30)
DUPLICATE_MIN_CHARS = 20

NOISE_VERSION = 3  # 2: thanks-for-sharing gratitude; 3: no duplicates for short texts,
# spam before duplicate, more en spam and ru gratitude phrases


@dataclass(frozen=True)
class NoiseContext:
    """What a rule may know besides the message itself."""

    reply_target: StoredMessage | None = None
    history: Mapping[str, Sequence[ChronoKey]] = field(default_factory=dict[str, list[ChronoKey]])
    """Fingerprint → positions of the chat's messages with that text (any order)."""


type Rule = Callable[[StoredMessage, NoiseContext], str | None]


def _has_media(msg: StoredMessage) -> bool:
    return msg.media_type not in (MediaType.NONE, MediaType.STICKER)


def service_message(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    return REASON_SERVICE if msg.is_service else None


def sticker_or_emoji_only(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    if msg.media_type is MediaType.STICKER:
        return REASON_STICKER
    if not _has_media(msg) and is_emoji_only(msg.text):
        return REASON_EMOJI_ONLY
    return None


def gratitude(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    text = msg.text.strip()
    if not text:
        return None
    if text in raw_entries(GRATITUDE) or fold(text) in folded_entries(GRATITUDE):
        return REASON_GRATITUDE
    return None


def short_without_value(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    if _has_media(msg) or len(msg.text) >= SHORT_LIMIT or looks_like_question(msg.text):
        return None
    target = ctx.reply_target
    if target is not None and looks_like_question(target.text):
        return None
    return REASON_SHORT


def duplicate(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    if len(fold(msg.text)) < DUPLICATE_MIN_CHARS:
        return None
    here = chrono_key(msg)
    start = msg.date - DUPLICATE_WINDOW
    for other in ctx.history.get(fingerprint(msg.text), ()):
        if other < here and other[0] >= start:
            return REASON_DUPLICATE
    return None


def spam_patterns(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    folded = fold(msg.text)
    if not contains_phrase(folded, folded_entries(SPAM_OFFERS)):
        return None
    if extract_urls(msg.text) or contains_phrase(folded, folded_entries(SPAM_CONTACTS)):
        return REASON_SPAM
    return None


RULES: tuple[Rule, ...] = (
    service_message,
    sticker_or_emoji_only,
    gratitude,
    short_without_value,
    spam_patterns,
    duplicate,
)


def classify(msg: StoredMessage, ctx: NoiseContext) -> str | None:
    """The noise reason of the first matching rule, or None for a useful message."""
    for rule in RULES:
        reason = rule(msg, ctx)
        if reason is not None:
            return reason
    return None


def fingerprint_index(messages: Sequence[StoredMessage]) -> dict[str, list[ChronoKey]]:
    index: defaultdict[str, list[ChronoKey]] = defaultdict(list)
    for msg in messages:
        if fold(msg.text):
            index[fingerprint(msg.text)].append(chrono_key(msg))
    return dict(index)


class NoiseStage:
    name = "noise"
    version = NOISE_VERSION
    depends_on: str | None = None

    async def run(self, deps: StageDeps, limit: int) -> int:
        pending = await deps.messages.pending_for(self.name, self.version, self.depends_on, limit)
        if not pending:
            return 0
        targets = await deps.messages.get_many(
            [(m.source, m.chat_id, m.reply_to) for m in pending if m.reply_to is not None]
        )
        by_chat: defaultdict[tuple[Source, str], list[StoredMessage]] = defaultdict(list)
        for msg in pending:
            by_chat[(msg.source, msg.chat_id)].append(msg)

        results: list[StageResult] = []
        for (source, chat_id), msgs in by_chat.items():
            since = min(m.date for m in msgs) - DUPLICATE_WINDOW
            history = fingerprint_index(await deps.messages.chat_window(source, chat_id, since))
            for msg in msgs:
                ctx = NoiseContext(reply_target=_target(msg, targets), history=history)
                reason = classify(msg, ctx)
                results.append(
                    StageResult(
                        key=msg.key, values={"is_noise": reason is not None, "noise_reason": reason}
                    )
                )
        await deps.messages.mark(self.name, self.version, results)
        return len(results)


def _target(msg: StoredMessage, targets: dict[MessageKey, StoredMessage]) -> StoredMessage | None:
    if msg.reply_to is None:
        return None
    return targets.get((msg.source, msg.chat_id, msg.reply_to))
