"""Behaviour that spans the work packages: one ref display, title selectors for `run --once`."""

from __future__ import annotations

import pytest

from chatimport.library import ChatEntry, Library
from chatimport.ports import ChatImportError, ResolvedChat, ResolveStatus
from chatimport.refs import display_ref
from chatimport.resolution import display_ref as status_ref
from chatimport.resolution import select_for_once
from tests.fakes import CHAT_ID, FakeGateway

ACUTE = chr(0x301)
COMPOSED_TITLE = "Caf" + chr(0xE9) + " Noticias"
DECOMPOSED_UPPER = "CAFE" + ACUTE + " NOTICIAS"
CYRILLIC_TITLE = "".join(chr(c) for c in (0x41D, 0x43E, 0x432, 0x43E, 0x441, 0x442, 0x438))


def gateway_with(title: str) -> FakeGateway:
    gateway = FakeGateway()
    gateway.refs["@news"] = ResolvedChat(
        "@news", ResolveStatus.FOUND, chat_id=CHAT_ID, title=title, username="news"
    )
    return gateway


@pytest.mark.parametrize(
    ("title", "selector"),
    [
        (COMPOSED_TITLE, DECOMPOSED_UPPER),
        (CYRILLIC_TITLE, "  " + CYRILLIC_TITLE.upper() + " "),
        (COMPOSED_TITLE, "@NEWS"),
        (COMPOSED_TITLE, str(CHAT_ID)),
    ],
)
async def test_run_once_selects_a_chat_by_any_form_of_its_title_username_or_id(
    title: str, selector: str
) -> None:
    library = Library((ChatEntry("@news"),))

    chosen = await select_for_once(gateway_with(title), library, selector)

    assert [item.resolved.chat_id for item in chosen] == [CHAT_ID]


async def test_run_once_with_an_unknown_selector_is_an_error() -> None:
    library = Library((ChatEntry("@news"),))

    with pytest.raises(ChatImportError, match="no library chat"):
        await select_for_once(gateway_with(COMPOSED_TITLE), library, "something else")


def test_invites_are_shown_the_same_way_with_and_without_a_digest() -> None:
    plain = display_ref("https://t.me/+SECRETHASH123")
    with_digest = status_ref("https://t.me/+SECRETHASH123")

    assert plain == "t.me/+SEC..."
    assert with_digest.startswith(plain + "#")
    assert "SECRETHASH" not in with_digest
    assert status_ref("https://t.me/+OTHERHASH999") != with_digest


def test_public_refs_are_shown_unchanged() -> None:
    assert display_ref("  @news ", digest=True) == "@news"
