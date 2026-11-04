from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from chatimport.ports import ResolvedChat, ResolveStatus
from chatimport.telegram.resolve import (
    InviteInfo,
    ParsedRef,
    RefKind,
    entity_kind,
    parse_ref,
    resolve_ref,
)


@dataclass
class Chat:
    pid: int
    title: str = ""
    deactivated: bool = False
    username: str | None = None


@dataclass
class Channel:
    pid: int
    title: str = ""
    megagroup: bool = False
    username: str | None = None


@dataclass
class User:
    pid: int
    first_name: str = "Person"
    bot: bool = False
    username: str | None = None


@dataclass
class ChannelForbidden:
    pid: int
    title: str = "Forbidden"


@dataclass
class ChatForbidden:
    pid: int
    title: str = "Forbidden"


@dataclass
class FakeLookup:
    usernames: dict[str, Any] = field(default_factory=dict[str, Any])
    invites: dict[str, InviteInfo] = field(default_factory=dict[str, InviteInfo])
    dialogs: list[Any] = field(default_factory=list[Any])
    error: BaseException | None = None
    calls: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    async def get_entity_by_username(self, username: str) -> Any | None:
        self.calls.append(("username", username))
        if self.error:
            raise self.error
        return self.usernames.get(username)

    async def check_invite(self, invite_hash: str) -> InviteInfo | None:
        self.calls.append(("invite", invite_hash))
        if self.error:
            raise self.error
        return self.invites.get(invite_hash)

    async def dialog_entities(self) -> list[Any]:
        self.calls.append(("dialogs", ""))
        if self.error:
            raise self.error
        return list(self.dialogs)

    def peer_id(self, entity: Any) -> int:
        return entity.pid


UNICODE_TITLE = (
    "\u0427\u0430\u0442 \u2014 "
    "\u041c\u043e\u043d\u0442\u0435\u0432\u0438\u0434\u0435\u043e "
    "\U0001f1fa\U0001f1fe"
)


def public(value: str) -> ParsedRef:
    return ParsedRef(RefKind.PUBLIC, value)


def invite(value: str) -> ParsedRef:
    return ParsedRef(RefKind.INVITE, value)


def title(value: str) -> ParsedRef:
    return ParsedRef(RefKind.TITLE, value)


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("https://t.me/example_chat", public("example_chat")),
        ("http://t.me/example_chat", public("example_chat")),
        ("t.me/example_chat", public("example_chat")),
        ("www.t.me/example_chat", public("example_chat")),
        ("https://www.t.me/example_chat", public("example_chat")),
        ("https://telegram.me/example_chat", public("example_chat")),
        ("HTTPS://T.ME/Example_Chat", public("Example_Chat")),
        ("https://t.me/example_chat/", public("example_chat")),
        ("https://t.me/example_chat//", public("example_chat")),
        ("https://t.me/example_chat?start=abc", public("example_chat")),
        ("https://t.me/example_chat#frag", public("example_chat")),
        ("https://t.me/example_chat/4512", public("example_chat")),
        ("https://t.me/example_chat/4512?single", public("example_chat")),
        ("  https://t.me/example_chat  ", public("example_chat")),
        ("@example_chat", public("example_chat")),
        ("@Example_Chat", public("Example_Chat")),
        ("  @example_chat\n", public("example_chat")),
        ("@abc", public("abc")),
        ("@a" + "b" * 31, public("a" + "b" * 31)),
        ("https://t.me/+AbC-dEf_123", invite("AbC-dEf_123")),
        ("t.me/+AbCdEf", invite("AbCdEf")),
        ("https://t.me/+AbCdEf/", invite("AbCdEf")),
        ("https://t.me/joinchat/AbCdEf", invite("AbCdEf")),
        ("https://t.me/JoinChat/AbCdEf", invite("AbCdEf")),
        ("https://t.me/joinchat/AbCdEf?x=1", invite("AbCdEf")),
        (
            "https://t.me/c/1234567890/4512",
            ParsedRef(RefKind.NUMERIC, "1234567890", -1001234567890),
        ),
        ("https://t.me/c/1234567890", ParsedRef(RefKind.NUMERIC, "1234567890", -1001234567890)),
        ("-1001234567890", ParsedRef(RefKind.NUMERIC, "-1001234567890", -1001234567890)),
        ("1234567890", ParsedRef(RefKind.NUMERIC, "1234567890", 1234567890)),
        ("-4567", ParsedRef(RefKind.NUMERIC, "-4567", -4567)),
        ("  -1001234567890  ", ParsedRef(RefKind.NUMERIC, "-1001234567890", -1001234567890)),
        ("0", ParsedRef(RefKind.NUMERIC, "0", 0)),
        ("Example group", title("Example group")),
        ("  Example group  ", title("Example group")),
        (
            UNICODE_TITLE,
            title(UNICODE_TITLE),
        ),
        ("\u6771\u4eac \u30c1\u30e3\u30c3\u30c8", title("\u6771\u4eac \u30c1\u30e3\u30c3\u30c8")),
        ("Chat 2024", title("Chat 2024")),
        ("12345 chat", title("12345 chat")),
        ("1.5", title("1.5")),
        ("--5", title("--5")),
        ("+123", title("+123")),
        ("t.me is great", title("t.me is great")),
        ("@everyone chat", title("@everyone chat")),
        ("@ab", title("@ab")),
        ("@", title("@")),
        ("@" + "a" * 33, title("@" + "a" * 33)),
        ("@1abc", title("@1abc")),
        ("@abc-def", title("@abc-def")),
        ("", title("")),
        ("   ", title("")),
        ("https://t.me/", title("https://t.me/")),
        ("https://t.me/+", title("https://t.me/+")),
        ("https://t.me/c/abc", title("https://t.me/c/abc")),
        ("https://example.com/example_chat", title("https://example.com/example_chat")),
        ("https://t.me/joinchat/", title("https://t.me/joinchat/")),
    ],
)
def test_parse_ref(ref: str, expected: ParsedRef) -> None:
    assert parse_ref(ref) == expected


def test_channel_post_link_of_a_short_channel_id_is_a_marked_numeric_ref() -> None:
    parsed = parse_ref("https://t.me/c/1234567/9")
    assert parsed.kind is RefKind.NUMERIC
    assert parsed.number == -1000001234567


@pytest.mark.parametrize(
    ("entity", "kind"),
    [
        (Chat(1), "group"),
        (Channel(1), "channel"),
        (Channel(1, megagroup=True), "supergroup"),
        (User(1), None),
        (User(1, bot=True), None),
        (ChannelForbidden(1), None),
        (ChatForbidden(1), None),
        (None, None),
        (object(), None),
    ],
)
def test_entity_kind(entity: Any, kind: str | None) -> None:
    assert entity_kind(entity) == kind


def test_channel_without_megagroup_attribute_is_a_channel() -> None:
    entity = type("Channel", (), {})()
    assert entity_kind(entity) == "channel"


async def test_public_username_resolves_to_a_group() -> None:
    lookup = FakeLookup(
        usernames={"example_chat": Channel(-1001234567890, "Example", True, "example_chat")}
    )
    result = await resolve_ref("https://t.me/example_chat", lookup)
    assert result == ResolvedChat(
        "https://t.me/example_chat",
        ResolveStatus.FOUND,
        chat_id=-1001234567890,
        title="Example",
        username="example_chat",
    )
    assert lookup.calls == [("username", "example_chat")]


async def test_public_username_is_passed_without_at_sign_and_with_original_case() -> None:
    lookup = FakeLookup(usernames={"Example_Chat": Channel(-1001234567890, "E")})
    result = await resolve_ref("@Example_Chat", lookup)
    assert result.status is ResolveStatus.FOUND
    assert lookup.calls == [("username", "Example_Chat")]


@pytest.mark.parametrize("entity", [User(5), User(5, bot=True), None])
async def test_public_username_of_a_person_or_bot_is_not_a_chat(entity: Any) -> None:
    lookup = FakeLookup(usernames={} if entity is None else {"someone": entity})
    result = await resolve_ref("@someone", lookup)
    if entity is None:
        assert result.status is ResolveStatus.NOT_FOUND
    else:
        assert result.status is ResolveStatus.NOT_A_CHAT
        assert result.chat_id is None


async def test_public_username_of_a_basic_group_and_channel() -> None:
    lookup = FakeLookup(
        usernames={"old_group": Chat(-77, "Old group"), "news": Channel(-1002000000000, "News")}
    )
    assert (await resolve_ref("@old_group", lookup)).chat_id == -77
    assert (await resolve_ref("@news", lookup)).chat_id == -1002000000000


async def test_empty_username_is_reported_as_none() -> None:
    lookup = FakeLookup(usernames={"abc": Channel(-1001000000000, "T", username="")})
    result = await resolve_ref("@abc", lookup)
    assert result.username is None


async def test_lookup_errors_propagate_unchanged() -> None:
    boom = RuntimeError("network down")
    for ref in ("@abc", "t.me/+hash", "-1001234567890", "Some title"):
        with pytest.raises(RuntimeError, match="network down"):
            await resolve_ref(ref, FakeLookup(error=boom))


async def test_invite_for_a_member_chat_is_found() -> None:
    entity = Channel(-1001234567890, "Private", True)
    lookup = FakeLookup(invites={"hash": InviteInfo(True, "Private", entity)})
    result = await resolve_ref("https://t.me/+hash", lookup)
    assert result.status is ResolveStatus.FOUND
    assert (result.chat_id, result.title) == (-1001234567890, "Private")
    assert lookup.calls == [("invite", "hash")]


async def test_invite_for_a_non_member_never_joins() -> None:
    lookup = FakeLookup(invites={"hash": InviteInfo(False, "Secret club")})
    result = await resolve_ref("https://t.me/joinchat/hash", lookup)
    assert result.status is ResolveStatus.NEED_TO_JOIN
    assert result.title == "Secret club"
    assert result.chat_id is None
    assert "join" in result.detail
    assert lookup.calls == [("invite", "hash")]
    assert not [name for name in dir(lookup) if "join" in name.lower()]


async def test_invite_marked_member_without_entity_still_needs_joining() -> None:
    lookup = FakeLookup(invites={"hash": InviteInfo(True, "X", None)})
    result = await resolve_ref("t.me/+hash", lookup)
    assert result.status is ResolveStatus.NEED_TO_JOIN
    assert result.chat_id is None


async def test_invalid_or_expired_invite_is_not_found() -> None:
    result = await resolve_ref("t.me/+gone", FakeLookup())
    assert result.status is ResolveStatus.NOT_FOUND
    assert "invalid" in result.detail


async def test_invite_pointing_at_a_person_is_not_a_chat() -> None:
    lookup = FakeLookup(invites={"h": InviteInfo(True, "P", User(9))})
    assert (await resolve_ref("t.me/+h", lookup)).status is ResolveStatus.NOT_A_CHAT


@pytest.mark.parametrize(
    "ref",
    ["-1001234567890", "1234567890", "-1234567890", "https://t.me/c/1234567890/12"],
)
async def test_numeric_aliases_of_a_supergroup(ref: str) -> None:
    lookup = FakeLookup(dialogs=[Channel(-1001234567890, "Super", True)])
    result = await resolve_ref(ref, lookup)
    if ref == "-1234567890":
        assert result.status is ResolveStatus.NOT_FOUND
    else:
        assert result.status is ResolveStatus.FOUND
        assert result.chat_id == -1001234567890


@pytest.mark.parametrize("ref", ["-4567", "4567"])
async def test_numeric_aliases_of_a_basic_group(ref: str) -> None:
    lookup = FakeLookup(dialogs=[Chat(-4567, "Basic")])
    result = await resolve_ref(ref, lookup)
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -4567)


async def test_numeric_ref_not_among_dialogs_is_not_found() -> None:
    lookup = FakeLookup(dialogs=[Channel(-1009999999999, "Other", True)])
    result = await resolve_ref("-1001234567890", lookup)
    assert result.status is ResolveStatus.NOT_FOUND
    assert result.detail == "not among your dialogs"


async def test_numeric_ref_of_a_user_is_not_a_chat() -> None:
    lookup = FakeLookup(dialogs=[User(5551234)])
    assert (await resolve_ref("5551234", lookup)).status is ResolveStatus.NOT_A_CHAT


async def test_numeric_ref_prefers_the_group_over_a_user_with_the_same_digits() -> None:
    lookup = FakeLookup(dialogs=[User(1234567890), Channel(-1001234567890, "Super", True)])
    result = await resolve_ref("1234567890", lookup)
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -1001234567890)


async def test_numeric_zero_matches_nothing() -> None:
    lookup = FakeLookup(dialogs=[Chat(-1, "G")])
    assert (await resolve_ref("0", lookup)).status is ResolveStatus.NOT_FOUND


async def test_channel_link_of_a_short_channel_id_finds_the_channel() -> None:
    lookup = FakeLookup(dialogs=[Channel(-1000001234567, "Old channel")])
    result = await resolve_ref("https://t.me/c/1234567/9", lookup)
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -1000001234567)


async def test_bare_short_channel_number_finds_the_marked_channel() -> None:
    lookup = FakeLookup(dialogs=[Channel(-1000001234567, "Old channel")])
    result = await resolve_ref("1234567", lookup)
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -1000001234567)


async def test_title_matches_exactly_and_uniquely() -> None:
    lookup = FakeLookup(
        dialogs=[
            Channel(-1001, "Montevideo chat", True),
            Channel(-1002, "Other", True),
            User(7),
        ]
    )
    result = await resolve_ref("  Montevideo chat ", lookup)
    assert (result.status, result.chat_id, result.title) == (
        ResolveStatus.FOUND,
        -1001,
        "Montevideo chat",
    )
    assert result.ref == "  Montevideo chat "


@pytest.mark.parametrize(
    "ref", ["montevideo chat", "MONTEVIDEO CHAT", "Montevideo", "Montevideo chat!"]
)
async def test_title_is_an_exact_case_sensitive_match(ref: str) -> None:
    lookup = FakeLookup(dialogs=[Channel(-1001, "Montevideo chat", True)])
    result = await resolve_ref(ref, lookup)
    assert result.status is ResolveStatus.NOT_FOUND


async def test_title_with_unicode_and_emoji_matches() -> None:
    lookup = FakeLookup(
        dialogs=[
            Chat(
                -5,
                UNICODE_TITLE,
            )
        ]
    )
    result = await resolve_ref(
        UNICODE_TITLE,
        lookup,
    )
    assert result.chat_id == -5


async def test_two_dialogs_with_the_same_title_are_ambiguous() -> None:
    lookup = FakeLookup(dialogs=[Chat(-1, "Same"), Channel(-1002, "Same")])
    result = await resolve_ref("Same", lookup)
    assert result.status is ResolveStatus.AMBIGUOUS
    assert result.chat_id is None
    assert result.title == "Same"
    assert "link" in result.detail


async def test_person_with_a_matching_name_is_ignored_in_title_search() -> None:
    lookup = FakeLookup(dialogs=[User(1, first_name="Same"), Channel(-1002, "Same")])
    result = await resolve_ref("Same", lookup)
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -1002)


async def test_missing_title_is_not_found() -> None:
    result = await resolve_ref("Nothing here", FakeLookup(dialogs=[Chat(-1, "Other")]))
    assert result.status is ResolveStatus.NOT_FOUND


@pytest.mark.parametrize("ref", ["", "   "])
async def test_empty_ref_matches_nothing(ref: str) -> None:
    lookup = FakeLookup(dialogs=[Chat(-1, "Other"), Chat(-2, "Third")])
    assert (await resolve_ref(ref, lookup)).status is ResolveStatus.NOT_FOUND


async def test_title_that_looks_like_a_number_is_resolved_as_a_number() -> None:
    lookup = FakeLookup(dialogs=[Chat(-5, "2024")])
    assert (await resolve_ref("2024", lookup)).status is ResolveStatus.NOT_FOUND


async def test_old_deactivated_group_does_not_make_a_title_ambiguous() -> None:
    lookup = FakeLookup(
        dialogs=[
            Chat(-5, "Neighbours", deactivated=True),
            Channel(-1001234567890, "Neighbours", True),
        ]
    )
    result = await resolve_ref("Neighbours", lookup)
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -1001234567890)


async def test_ref_in_the_result_is_the_original_text() -> None:
    lookup = FakeLookup(usernames={})
    result = await resolve_ref("  @nobody  ", lookup)
    assert result.ref == "  @nobody  "
    assert result.status is ResolveStatus.NOT_FOUND
