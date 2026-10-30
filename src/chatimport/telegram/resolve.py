"""Library refs to chats (spec §7.2). Parsing is pure; resolving goes through `EntityLookup`.

A ref never makes the account join anything: an invite for a chat the account is not in
yields `NEED_TO_JOIN`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from chatimport.ports import ResolvedChat, ResolveStatus

_URL: Final = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+)$", re.IGNORECASE)
_USERNAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")
_NUMBER: Final = re.compile(r"^-?\d+$")
_CHANNEL_ID_BASE: Final = 10**12


class RefKind(StrEnum):
    PUBLIC = "public"
    INVITE = "invite"
    NUMERIC = "numeric"
    TITLE = "title"


@dataclass(frozen=True, slots=True)
class ParsedRef:
    kind: RefKind
    value: str
    number: int | None = None


@dataclass(frozen=True, slots=True)
class InviteInfo:
    is_member: bool
    title: str | None = None
    entity: Any = None


class EntityLookup(Protocol):
    async def get_entity_by_username(self, username: str) -> Any | None: ...

    async def check_invite(self, invite_hash: str) -> InviteInfo | None:
        """None when the invite is invalid or expired."""
        ...

    async def dialog_entities(self) -> list[Any]: ...

    def peer_id(self, entity: Any) -> int:
        """The marked chat id (`-100…` for channels)."""
        ...


def parse_ref(ref: str) -> ParsedRef:
    text = ref.strip()
    url = _URL.match(text)
    if url:
        return _parse_path(url.group(1), text)
    if text.startswith("@") and _USERNAME.match(text[1:]):
        return ParsedRef(RefKind.PUBLIC, text[1:])
    if _NUMBER.match(text):
        return ParsedRef(RefKind.NUMERIC, text, int(text))
    return ParsedRef(RefKind.TITLE, text)


def _parse_path(path: str, original: str) -> ParsedRef:
    segments = path.split("?", 1)[0].split("#", 1)[0].strip("/").split("/")
    first = segments[0]
    if first.startswith("+") and len(first) > 1:
        return ParsedRef(RefKind.INVITE, first[1:])
    if first.lower() == "joinchat":
        if len(segments) > 1 and segments[1]:
            return ParsedRef(RefKind.INVITE, segments[1])
        return ParsedRef(RefKind.TITLE, original)
    if first == "c" and len(segments) > 1 and segments[1].isdigit():
        return ParsedRef(RefKind.NUMERIC, segments[1], -(_CHANNEL_ID_BASE + int(segments[1])))
    if _USERNAME.match(first):
        return ParsedRef(RefKind.PUBLIC, first)
    return ParsedRef(RefKind.TITLE, original)


def entity_kind(entity: Any) -> str | None:
    """`group`, `supergroup` or `channel`; None for people, bots and unreachable chats."""
    match type(entity).__name__:
        case "Chat":
            return "group"
        case "Channel":
            return "supergroup" if getattr(entity, "megagroup", False) else "channel"
        case _:
            return None


async def resolve_ref(ref: str, lookup: EntityLookup) -> ResolvedChat:
    parsed = parse_ref(ref)
    match parsed.kind:
        case RefKind.PUBLIC:
            entity = await lookup.get_entity_by_username(parsed.value)
            if entity is None:
                return ResolvedChat(ref, ResolveStatus.NOT_FOUND, detail="no such username")
            return _found(ref, entity, lookup)
        case RefKind.INVITE:
            return await _resolve_invite(ref, parsed.value, lookup)
        case RefKind.NUMERIC:
            return await _resolve_number(ref, parsed, lookup)
        case _:
            return await _resolve_title(ref, parsed.value, lookup)


def _found(ref: str, entity: Any, lookup: EntityLookup) -> ResolvedChat:
    if entity_kind(entity) is None:
        return ResolvedChat(ref, ResolveStatus.NOT_A_CHAT, detail="not a group or channel")
    return ResolvedChat(
        ref,
        ResolveStatus.FOUND,
        chat_id=lookup.peer_id(entity),
        title=getattr(entity, "title", None),
        username=getattr(entity, "username", None) or None,
    )


async def _resolve_invite(ref: str, invite_hash: str, lookup: EntityLookup) -> ResolvedChat:
    info = await lookup.check_invite(invite_hash)
    if info is None:
        return ResolvedChat(ref, ResolveStatus.NOT_FOUND, detail="invite is invalid or expired")
    if not info.is_member or info.entity is None:
        return ResolvedChat(
            ref,
            ResolveStatus.NEED_TO_JOIN,
            title=info.title,
            detail="join the chat from your account, then reload the library",
        )
    return _found(ref, info.entity, lookup)


async def _resolve_number(ref: str, parsed: ParsedRef, lookup: EntityLookup) -> ResolvedChat:
    number = parsed.number or 0
    wanted = {number}
    if number > 0:
        wanted |= {-number, -(_CHANNEL_ID_BASE + number)}
    matches = [
        entity for entity in await lookup.dialog_entities() if lookup.peer_id(entity) in wanted
    ]
    if not matches:
        return ResolvedChat(ref, ResolveStatus.NOT_FOUND, detail="not among your dialogs")
    chats = [entity for entity in matches if entity_kind(entity) is not None]
    return _found(ref, (chats or matches)[0], lookup)


async def _resolve_title(ref: str, title: str, lookup: EntityLookup) -> ResolvedChat:
    matches = [
        entity
        for entity in await lookup.dialog_entities()
        if entity_kind(entity) is not None
        and not getattr(entity, "deactivated", False)
        and getattr(entity, "title", None) == title
    ]
    if not matches:
        return ResolvedChat(ref, ResolveStatus.NOT_FOUND, detail="no dialog with this title")
    if len(matches) > 1:
        return ResolvedChat(
            ref,
            ResolveStatus.AMBIGUOUS,
            title=title,
            detail="several dialogs share this title; use a link",
        )
    return _found(ref, matches[0], lookup)
