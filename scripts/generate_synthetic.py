"""Generate synthetic Telegram Desktop exports for tests, demos and manual checks.

The output imitates real migrant chats in Montevideo (Russian, Spanish, English): topics,
message lengths, reply chains, edits, media, service events, gratitude, flood, spam and
duplicates, at rates measured on real exports (aggregates only). All text comes from the
invented phrase bank `tests/fixtures/synthetic/phrasebank.json`; nothing real is copied.

Deterministic: the same seed always writes byte-identical files.

Usage: uv run python scripts/generate_synthetic.py [--check] [--out DIR] [--seed N]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic"
PHRASEBANK = FIXTURES / "phrasebank.json"
SEED = 20261019
LOCAL_TZ = timezone(timedelta(hours=-3))  # Montevideo; Desktop writes local "date"
SLOT = re.compile(r"\{(\w+)\}")

type Json = dict[str, Any]
type Text = str | list[str | Json]

# Rates measured on ~177k real messages (8 chats): replies ~60%, edited ~28%, question
# marks ~18%, short messages ~7%, photos ~5%, forwards ~0.7%, service ~0.4%.
EDITED_RATE = 0.28
PHOTO_QUESTION_RATE = 0.05
DUPLICATE_THREAD_RATE = 0.02
REPLY_COUNTS = (0, 1, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 11, 14)
ANSWER_PARTS = (1, 1, 1, 1, 1, 1, 2, 2, 2, 3)  # p90 length ~200 chars, like real chats
REPLY_KINDS = (
    ("answer", 55),
    ("followup", 7),
    ("short", 5),
    ("gratitude", 6),
    ("continue", 12),
    ("mention", 4),
    ("voice", 3),
    ("photo", 2),
    ("sticker", 2),
    ("video_note", 1),
)
URL_KEEP = 0.25
OPENER_RATE = 0.8
CLOSER_RATE = 0.4
ASKER_RATE = 0.5
FOLLOWUP_ASKER_RATE = 0.4
UNLINKED_ANSWER_RATE = 0.2
GAP_MEDIAN_SEC = 50.0
GAP_SIGMA = 1.7


@dataclass(frozen=True)
class ChatSpec:
    file: str
    name: str
    type: str
    id: int
    langs: dict[str, float]
    topics: dict[str, float]
    threads: int
    members: dict[str, int]
    start: datetime
    days: int
    spam_rate: float


CHATS: tuple[ChatSpec, ...] = (
    ChatSpec(
        file="ru_banks_docs.json",
        name="Uruguay: Banks and Documents (synthetic)",
        type="private_supergroup",
        id=1800000001,
        langs={"ru": 0.92, "es": 0.05, "en": 0.03},
        topics={"banks": 3, "documents": 3, "housing": 2, "health": 1, "work": 1, "telecom": 1},
        threads=105,
        members={"ru": 70, "es": 6, "en": 4},
        start=datetime(2026, 8, 20, 11, 0, tzinfo=UTC),
        days=50,
        spam_rate=0.02,
    ),
    ChatSpec(
        file="ru_it.json",
        name="IT in Uruguay (synthetic)",
        type="public_supergroup",
        id=1800000002,
        langs={"ru": 0.85, "en": 0.15},
        topics={"it": 3, "work": 3, "banks": 1, "meetups": 1, "telecom": 1},
        threads=60,
        members={"ru": 50, "en": 6},
        start=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
        days=45,
        spam_rate=0.01,
    ),
    ChatSpec(
        file="es_comunidad.json",
        name="Comunidad de Extranjeros en Montevideo (sintético)",
        type="public_supergroup",
        id=1800000003,
        langs={"es": 0.85, "en": 0.08, "ru": 0.07},
        topics={"documents": 3, "housing": 3, "banks": 2, "health": 1, "meetups": 1},
        threads=48,
        members={"es": 40, "en": 5, "ru": 5},
        start=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        days=40,
        spam_rate=0.02,
    ),
    ChatSpec(
        file="en_expats.json",
        name="Montevideo Expats English (synthetic)",
        type="public_supergroup",
        id=1800000004,
        langs={"en": 0.8, "es": 0.12, "ru": 0.08},
        topics={"documents": 2, "housing": 2, "banks": 2, "work": 1, "health": 1, "meetups": 1},
        threads=48,
        members={"en": 35, "es": 6, "ru": 4},
        start=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        days=40,
        spam_rate=0.01,
    ),
)


@dataclass(frozen=True)
class Member:
    name: str
    user_id: int
    lang: str
    handle: str


@dataclass
class Draft:
    """A message before ids are assigned; `reply_to` points at another draft's key."""

    key: int
    at: datetime
    author: Member
    text: Text = ""
    reply_to: int | None = None
    extra: Json = field(default_factory=dict[str, Any])
    service_action: str | None = None


class Generator:
    def __init__(self, bank: Json, seed: int) -> None:
        self.bank = bank
        self.rng = random.Random(seed)  # noqa: S311 — reproducible test data, not security
        self.keys = 0

    # ------------------------------------------------------------------ helpers

    def _key(self) -> int:
        self.keys += 1
        return self.keys

    def _pick[T](self, items: list[T] | tuple[T, ...]) -> T:
        return items[self.rng.randrange(len(items))]

    def _weighted(self, weights: dict[str, float]) -> str:
        names = sorted(weights)
        return self.rng.choices(names, weights=[weights[n] for n in names], k=1)[0]

    def _gap(self) -> timedelta:
        seconds = self.rng.lognormvariate(math.log(GAP_MEDIAN_SEC), GAP_SIGMA)
        return timedelta(seconds=min(max(seconds, 3.0), 6 * 3600))

    def _fill(self, template: str, members: list[Member]) -> Text:
        """Fill slots; a URL or a mention turns the text into Desktop's entity list."""
        slots = cast("dict[str, list[str]]", self.bank["slots"])
        parts: list[str | Json] = []
        last = 0
        for match in SLOT.finditer(template):
            parts.append(template[last : match.start()])
            name = match.group(1)
            if name == "url":
                parts.append({"type": "link", "text": self._pick(slots["url"])})
            elif name == "mention":
                parts.append({"type": "mention", "text": f"@{self._pick(members).handle}"})
            else:
                parts.append(self._pick(slots[name]))
            last = match.end()
        parts.append(template[last:])
        merged: list[str | Json] = []
        for part in parts:
            if isinstance(part, str) and merged and isinstance(merged[-1], str):
                merged[-1] += part
            elif part != "":
                merged.append(part)
        if all(isinstance(p, str) for p in merged):
            return "".join(cast("list[str]", merged))
        return merged

    def _phrase(self, group: str, lang: str, members: list[Member]) -> Text:
        options = cast("dict[str, list[str]]", self.bank[group])
        return self._fill(self._pick(options[lang]), members)

    def _topic_phrase(self, topic: str, kind: str, lang: str, members: list[Member]) -> Text:
        by_lang = cast("dict[str, dict[str, list[str]]]", self.bank["topics"][topic])
        phrases = by_lang.get(lang) or by_lang["ru"]
        if kind != "answers":
            text = self._fill(self._pick(phrases[kind]), members)
            rate = ASKER_RATE if kind == "questions" else FOLLOWUP_ASKER_RATE
            if self.rng.random() < rate:
                asker = self._pick(self.bank["askers"][lang])
                if asker.endswith((",", ":")):
                    text = _lower_first(text)
                text = _join([asker, text], sep=" ")
            return text
        count = min(self._pick(ANSWER_PARTS), len(phrases[kind]))
        # Links are rare in real chats (~3% of messages): phrases with one are down-weighted.
        pool = [p for p in phrases[kind] if "{url}" not in p or self.rng.random() < URL_KEEP]
        chosen = self.rng.sample(pool or phrases[kind], min(count, len(pool or phrases[kind])))
        text = _join([self._fill(phrase, members) for phrase in chosen])
        # Real people rarely repeat a sentence verbatim; without this variety the duplicate
        # rule would flag a third of the corpus.
        if self.rng.random() < OPENER_RATE:
            text = _join([self._pick(self.bank["openers"][lang]), _lower_first(text)], sep=" ")
        if self.rng.random() < CLOSER_RATE:
            text = _join([text, self._pick(self.bank["closers"][lang])])
        return text

    def _author(self, members: list[Member], lang: str, exclude: Member | None = None) -> Member:
        same = [m for m in members if m.lang == lang and m is not exclude]
        return self._pick(same or [m for m in members if m is not exclude])

    def _maybe_edit(self, draft: Draft) -> None:
        if draft.text and self.rng.random() < EDITED_RATE:
            draft.extra["edited_after"] = self.rng.randint(20, 900)

    # ------------------------------------------------------------------ members

    def members(self, spec: ChatSpec) -> list[Member]:
        names = cast("dict[str, list[str]]", self.bank["names"])
        result: list[Member] = []
        for lang in sorted(spec.members):
            for _ in range(spec.members[lang]):
                index = len(result) + 1
                name = f"{self._pick(names[lang])} {self._pick(list(self.bank['initials'][lang]))}."
                result.append(
                    Member(name, spec.id * 100 + index, lang, f"member_{spec.id % 100}_{index:03d}")
                )
        return result

    # ------------------------------------------------------------------ threads

    def thread(self, spec: ChatSpec, members: list[Member], start: datetime) -> list[Draft]:
        lang = self._weighted(spec.langs)
        topic = self._weighted(spec.topics)
        asker = self._author(members, lang)
        root = Draft(
            self._key(), start, asker, self._topic_phrase(topic, "questions", lang, members)
        )
        if self.rng.random() < PHOTO_QUESTION_RATE:
            root.text = self._phrase("captions", lang, members)
            root.extra["photo"] = True
        self._maybe_edit(root)
        drafts = [root]
        answers: list[Draft] = []
        at = start
        for _ in range(self._pick(REPLY_COUNTS)):
            at += self._gap()
            kind = self.rng.choices(
                [k for k, _ in REPLY_KINDS], weights=[w for _, w in REPLY_KINDS], k=1
            )[0]
            draft = self._reply(kind, topic, lang, members, asker, root, answers, drafts, at)
            if draft is None:
                continue
            self._maybe_edit(draft)
            drafts.append(draft)
            if kind in ("answer", "mention", "voice", "photo"):
                answers.append(draft)
        if self.rng.random() < DUPLICATE_THREAD_RATE:
            later = at + timedelta(days=self.rng.randint(1, 10), seconds=self.rng.randint(0, 3600))
            drafts.append(Draft(self._key(), later, asker, root.text))
        return drafts

    def _reply(
        self,
        kind: str,
        topic: str,
        lang: str,
        members: list[Member],
        asker: Member,
        root: Draft,
        answers: list[Draft],
        drafts: list[Draft],
        at: datetime,
    ) -> Draft | None:
        target = root if not answers or self.rng.random() < 0.55 else self._pick(answers)
        if self.rng.random() < 0.35:
            target = drafts[-1]  # chains deepen the reply tree
        helper = self._author(members, lang, exclude=asker)
        if kind == "answer" and self.rng.random() < UNLINKED_ANSWER_RATE:
            return Draft(
                self._key(), at, helper, self._topic_phrase(topic, "answers", lang, members)
            )
        if kind == "answer":
            return Draft(
                self._key(),
                at,
                helper,
                self._topic_phrase(topic, "answers", lang, members),
                target.key,
            )
        if kind == "followup":
            if not answers:
                return None
            return Draft(
                self._key(),
                at,
                asker,
                self._topic_phrase(topic, "followups", lang, members),
                self._pick(answers).key,
            )
        if kind == "short":
            return Draft(
                self._key(),
                at,
                self._author(members, lang),
                self._phrase("short", lang, members),
                target.key,
            )
        if kind == "gratitude":
            if not answers:
                return None
            return Draft(
                self._key(),
                at,
                asker,
                self._phrase("gratitude", lang, members),
                self._pick(answers).key,
            )
        if kind == "continue":  # same thread by time proximity only, no reply link
            return Draft(
                self._key(), at, helper, self._topic_phrase(topic, "answers", lang, members)
            )
        if kind == "mention":
            text = self._fill(
                self._pick(cast("dict[str, list[str]]", self.bank["mention_tail"])[lang]), members
            )
            return Draft(self._key(), at, asker, text, root.key)
        if kind == "voice":
            return Draft(
                self._key(), at, helper, "", target.key, {"voice": self.rng.randint(4, 90)}
            )
        if kind == "photo":
            return Draft(self._key(), at, helper, "", target.key, {"photo": True})
        if kind == "sticker":
            return Draft(
                self._key(),
                at,
                helper,
                "",
                target.key,
                {"sticker": self._pick(self.bank["sticker_emoji"])},
            )
        return Draft(
            self._key(), at, helper, "", target.key, {"video_note": self.rng.randint(3, 40)}
        )

    def interlude(self, spec: ChatSpec, members: list[Member], at: datetime) -> list[Draft]:
        """Chat life between threads: joins, greetings, flood, spam, forwards, emoji."""
        lang = self._weighted(spec.langs)
        roll = self.rng.random()
        someone = self._author(members, lang)
        if roll < 0.06:
            return [Draft(self._key(), at, someone, service_action="join_group_by_link")]
        if roll < 0.10:
            return [Draft(self._key(), at, someone, self._phrase("greetings", lang, members))]
        if roll < 0.16:
            first = Draft(self._key(), at, someone, self._phrase("offtopic", lang, members))
            reply = Draft(
                self._key(),
                at + self._gap(),
                self._author(members, lang, someone),
                self._phrase("short", lang, members),
                first.key,
            )
            return [first, reply]
        if roll < 0.18:
            return [Draft(self._key(), at, someone, self._pick(self.bank["emoji_only"]))]
        if roll < 0.23:
            return [Draft(self._key(), at, someone, "", extra={"animation": True})]
        if roll < 0.25:
            forward = Draft(self._key(), at, someone, self._phrase("forwards", lang, members))
            forward.extra["forwarded_from"] = "Synthetic News Channel"
            return [forward]
        if roll < 0.25 + spec.spam_rate * 4:
            spam = cast("dict[str, list[list[str | Json]]]", self.bank["spam"])
            return [Draft(self._key(), at, someone, list(self._pick(spam[lang])))]
        return []

    # ------------------------------------------------------------------ chat

    def chat(self, spec: ChatSpec) -> Json:
        members = self.members(spec)
        # Exports start with service events too; every chat gets at least one join.
        drafts: list[Draft] = [
            Draft(self._key(), spec.start, self._pick(members), service_action="join_group_by_link")
        ]
        span = spec.days * 86400
        for index in range(spec.threads):
            offset = span * (index + self.rng.random()) / spec.threads
            start = _daytime(spec.start + timedelta(seconds=offset), self.rng)
            drafts += self.interlude(
                spec, members, start - timedelta(minutes=self.rng.randint(5, 90))
            )
            drafts += self.thread(spec, members, start)
        drafts.sort(key=lambda d: (d.at, d.key))
        ids = {d.key: index for index, d in enumerate(drafts, start=1)}
        messages = [_render(d, ids) for d in drafts]
        return {"name": spec.name, "type": spec.type, "id": spec.id, "messages": messages}


def _lower_first(text: Text) -> Text:
    """Lowercase the first letter after an opener, unless it starts an acronym or a name."""
    head = text if isinstance(text, str) else text[0]
    if not isinstance(head, str) or len(head) < 2 or not head[0].isupper() or head[1].isupper():
        return text
    lowered = head[0].lower() + head[1:]
    return lowered if isinstance(text, str) else [lowered, *text[1:]]


def _join(parts: list[Text], sep: str = ". ") -> Text:
    """Sentences into one message; entity lists stay entity lists."""
    if all(isinstance(part, str) for part in parts):
        return sep.join(cast("list[str]", parts))
    joined: list[str | Json] = []
    for index, part in enumerate(parts):
        if index:
            joined.append(sep)
        joined.extend([part] if isinstance(part, str) else part)
    merged: list[str | Json] = []
    for piece in joined:
        if isinstance(piece, str) and merged and isinstance(merged[-1], str):
            merged[-1] += piece
        else:
            merged.append(piece)
    return merged


def _daytime(at: datetime, rng: random.Random) -> datetime:
    """Move night-time starts (local) into the morning, like real chat activity."""
    local = at.astimezone(LOCAL_TZ)
    if local.hour < 8:
        local = local.replace(hour=8 + rng.randint(0, 3), minute=rng.randint(0, 59))
    return local.astimezone(UTC)


def _stamp(at: datetime) -> tuple[str, str]:
    at = at.replace(microsecond=0)
    return at.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat(), str(int(at.timestamp()))


def _entities(text: Text) -> list[Json]:
    if isinstance(text, str):
        return [{"type": "plain", "text": text}] if text else []
    return [{"type": "plain", "text": p} if isinstance(p, str) else p for p in text]


def _render(draft: Draft, ids: dict[int, int]) -> Json:
    date, unixtime = _stamp(draft.at)
    user = f"user{draft.author.user_id}"
    message: Json = {
        "id": ids[draft.key],
        "type": "message",
        "date": date,
        "date_unixtime": unixtime,
    }
    if draft.service_action:
        message["type"] = "service"
        message |= {"actor": draft.author.name, "actor_id": user, "action": draft.service_action}
        message |= {"inviter": "Group", "text": "", "text_entities": []}
        return message
    message |= {"from": draft.author.name, "from_id": user}
    if draft.reply_to is not None:
        message["reply_to_message_id"] = ids[draft.reply_to]
    if "edited_after" in draft.extra:
        edited, edited_unix = _stamp(draft.at + timedelta(seconds=draft.extra["edited_after"]))
        message |= {"edited": edited, "edited_unixtime": edited_unix}
    if "forwarded_from" in draft.extra:
        message["forwarded_from"] = draft.extra["forwarded_from"]
    message |= _media(draft, ids[draft.key])
    message |= {"text": draft.text, "text_entities": _entities(draft.text)}
    return message


def _media(draft: Draft, msg_id: int) -> Json:
    extra = draft.extra
    if extra.get("photo"):
        return {"photo": f"photos/photo_{msg_id}.jpg", "width": 1280, "height": 960}
    if "voice" in extra:
        return {
            "file": f"voice_messages/audio_{msg_id}.ogg",
            "media_type": "voice_message",
            "mime_type": "audio/ogg",
            "duration_seconds": extra["voice"],
        }
    if "video_note" in extra:
        return {
            "file": f"round_video_messages/round_{msg_id}.mp4",
            "media_type": "video_message",
            "mime_type": "video/mp4",
            "duration_seconds": extra["video_note"],
        }
    if "sticker" in extra:
        return {
            "file": "(File not included. Change data exporting settings to download.)",
            "media_type": "sticker",
            "sticker_emoji": extra["sticker"],
            "width": 512,
            "height": 512,
        }
    if extra.get("animation"):
        return {
            "file": "(File not included. Change data exporting settings to download.)",
            "media_type": "animation",
            "mime_type": "video/mp4",
        }
    return {}


def render_all(seed: int = SEED) -> dict[str, str]:
    bank = cast("Json", json.loads(PHRASEBANK.read_text(encoding="utf-8")))
    generator = Generator(bank, seed)
    return {
        spec.file: json.dumps(generator.chat(spec), ensure_ascii=False, indent=1) + "\n"
        for spec in CHATS
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic Telegram Desktop exports.")
    parser.add_argument("--check", action="store_true", help="fail if committed files differ")
    parser.add_argument("--out", type=Path, default=FIXTURES)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)

    outputs = render_all(args.seed)
    out = cast("Path", args.out)
    if args.check:
        stale = [
            name
            for name, content in outputs.items()
            if not (out / name).is_file()
            or (out / name).read_text(encoding="utf-8").replace("\r\n", "\n") != content
        ]
        if stale:
            sys.stderr.write(f"ERR synthetic fixtures are stale: {stale}. Run: just synthetic\n")
            return 1
        sys.stdout.write(f"ok  synthetic fixtures in sync ({len(outputs)} chats)\n")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (out / name).write_text(content, encoding="utf-8", newline="\n")
    counts = {name: content.count('"id": ') for name, content in outputs.items()}
    sys.stdout.write(f"ok  wrote {counts}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
