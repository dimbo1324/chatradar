from __future__ import annotations

import pytest

from chatimport.refs import ParsedRef, RefKind, display_ref, parse_ref
from chatimport.telegram import resolve

CAFE_NFC = "Caf\u00e9 Espa\u00f1a"
CAFE_NFD = "Cafe\u0301 Espan\u0303a"


@pytest.mark.parametrize(
    "ref",
    ["@Foo_bar", "t.me/foo_bar", "https://telegram.me/FOO_BAR", "https://t.me/foo_bar?x=1"],
)
def test_public_refs_of_one_chat_share_one_identity(ref: str) -> None:
    assert parse_ref(ref).identity == "@foo_bar"
    assert parse_ref(ref).username == "foo_bar"


@pytest.mark.parametrize(
    ("ref", "identity"),
    [
        ("https://t.me/+AbCdEf", "invite:AbCdEf"),
        ("t.me/joinchat/AbCdEf", "invite:AbCdEf"),
        ("-1001234567890", "-1001234567890"),
        ("https://t.me/c/1234567890/5", "-1001234567890"),
        ("  Book Club ", "Book Club"),
        ("@ab", "@ab"),
    ],
)
def test_identity_of_other_kinds(ref: str, identity: str) -> None:
    assert parse_ref(ref).identity == identity


def test_invite_hashes_keep_their_case() -> None:
    assert parse_ref("t.me/+AbC").identity != parse_ref("t.me/+abc").identity


def test_title_identity_ignores_the_unicode_form_of_accents() -> None:
    assert CAFE_NFC != CAFE_NFD
    assert parse_ref(CAFE_NFC).identity == parse_ref(CAFE_NFD).identity


def test_only_public_refs_have_a_username() -> None:
    assert parse_ref("Some title").username is None
    assert parse_ref("-5").username is None


@pytest.mark.parametrize(
    ("ref", "shown"),
    [
        ("https://t.me/+SECRETHASH123", "t.me/+SEC..."),
        ("  t.me/joinchat/SECRETHASH123 ", "t.me/+SEC..."),
        ("@public_name", "@public_name"),
        (" -100555 ", "-100555"),
        ("Plain title", "Plain title"),
    ],
)
def test_display_ref_masks_only_invite_hashes(ref: str, shown: str) -> None:
    assert display_ref(ref) == shown


def test_resolve_module_re_exports_the_parser() -> None:
    assert resolve.parse_ref is parse_ref
    assert resolve.ParsedRef is ParsedRef
    assert resolve.RefKind is RefKind
