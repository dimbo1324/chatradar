from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.library import (
    ChatEntry,
    Library,
    LibraryError,
    add_entry,
    identity_of,
    parse_library,
    set_enabled,
)

if TYPE_CHECKING:
    from pathlib import Path

NEWS = "\u041d\u043e\u0432\u043e\u0441\u0442\u0438"
NEWS_LOWER = "\u043d\u043e\u0432\u043e\u0441\u0442\u0438"
CAFE_NFC = "Caf\u00e9 Espa\u00f1a"
CAFE_NFD = "Cafe\u0301 Espan\u0303a"
SECRET = "SECRETHASH123"


def two(first: str, second: str) -> str:
    return f'[[chat]]\nref = "{first}"\n[[chat]]\nref = "{second}"\n'


@pytest.mark.parametrize(
    "second", ["t.me/foo", "https://telegram.me/FOO", "https://t.me/foo?x=1", "@foo"]
)
def test_duplicate_refs_across_link_styles(second: str) -> None:
    with pytest.raises(LibraryError, match="duplicate"):
        parse_library(two("@Foo", second))


def test_parse_library_rejects_nfc_nfd_duplicate_title() -> None:
    with pytest.raises(LibraryError, match="duplicate"):
        parse_library(two(CAFE_NFC, CAFE_NFD))


def test_add_entry_rejects_the_same_public_chat_in_another_link_style(path: Path) -> None:
    add_entry(path, "@Foo")
    with pytest.raises(LibraryError, match="already in the library"):
        add_entry(path, "https://telegram.me/foo")


def test_identity_of_delegates_to_the_one_parser() -> None:
    assert identity_of("https://telegram.me/Foo") == identity_of("@foo") == "@foo"


def test_library_find_ref_casefold_cyrillic() -> None:
    library = Library((ChatEntry(NEWS),))
    assert library.find(NEWS_LOWER) is library.entries[0]


def test_library_find_title_ref_in_another_unicode_form() -> None:
    library = Library((ChatEntry(CAFE_NFC),))
    assert library.find(CAFE_NFD) is library.entries[0]


def test_library_find_name_in_another_unicode_form() -> None:
    library = Library((ChatEntry("-5", CAFE_NFD),))
    assert library.find(CAFE_NFC.upper()) is library.entries[0]


def test_set_enabled_finds_a_title_ref_typed_in_lower_case(path: Path) -> None:
    add_entry(path, NEWS)
    set_enabled(path, NEWS_LOWER, False)
    assert parse_library(path.read_text(encoding="utf-8")).entries[0].enabled is False


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "chats.toml"


def test_library_errors_mask_invite_hashes() -> None:
    link = f"https://t.me/+{SECRET}"
    with pytest.raises(LibraryError) as duplicate:
        parse_library(two(link, link))
    with pytest.raises(LibraryError) as unknown_key:
        parse_library(f'[[chat]]\nref = "{link}"\nnope = 1\n')
    for error in (duplicate.value, unknown_key.value):
        assert SECRET not in str(error)
        assert "t.me/+SEC..." in str(error)


def test_editing_errors_mask_invite_hashes(path: Path) -> None:
    link = f"https://t.me/+{SECRET}"
    add_entry(path, link)
    with pytest.raises(LibraryError) as again:
        add_entry(path, link)
    with pytest.raises(LibraryError) as missing:
        set_enabled(path, f"https://t.me/+{SECRET}X", False)
    for error in (again.value, missing.value):
        assert SECRET not in str(error)


def test_unlocatable_block_error_masks_the_invite_hash(path: Path) -> None:
    path.write_text(f'chat = [{{ref = "https://t.me/+{SECRET}"}}]\n', encoding="utf-8")
    with pytest.raises(LibraryError, match="cannot locate") as error:
        set_enabled(path, f"https://t.me/+{SECRET}", False)
    assert SECRET not in str(error.value)
