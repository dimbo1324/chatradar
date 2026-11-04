"""Library refs to chats (spec §7.2). Parsing is pure; resolving goes through `EntityLookup`.

A ref never makes the account join anything: an invite for a chat the account is not in
yields `NEED_TO_JOIN`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from chatimport.ports import ResolvedChat, ResolveStatus
from chatimport.refs import CHANNEL_ID_BASE, ParsedRef, RefKind, parse_ref

__all__ = [
    "EntityLookup",
    "InviteInfo",
    "ParsedRef",
    "RefKind",
    "entity_kind",
    "parse_ref",
    "resolve_ref",
]


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
        wanted |= {-number, -(CHANNEL_ID_BASE + number)}
    matches = [
        entity for entity in await lookup.dialog_entities() if lookup.peer_id(entity) in wanted
    ]
    if not matches:
        return ResolvedChat(ref, ResolveStatus.NOT_FOUND, detail="not among your dialogs")
    chats = [entity for entity in matches if entity_kind(entity) is not None]
    return _found(ref, (chats or matches)[0], lookup)


def _nfc(text: object) -> str | None:
    return unicodedata.normalize("NFC", text) if isinstance(text, str) else None


async def _resolve_title(ref: str, title: str, lookup: EntityLookup) -> ResolvedChat:
    """Exact title match, as the spec says; only the Unicode encoding of accents is forgiven."""
    wanted = _nfc(title)
    matches = [
        entity
        for entity in await lookup.dialog_entities()
        if entity_kind(entity) is not None
        and not getattr(entity, "deactivated", False)
        and _nfc(getattr(entity, "title", None)) == wanted
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
