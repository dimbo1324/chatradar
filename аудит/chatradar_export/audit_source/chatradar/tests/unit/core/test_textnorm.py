from __future__ import annotations

import unicodedata

import pytest

from chatimport.storage.layout import chat_folder_name, slugify
from chatimport.textnorm import fold, transliterate


def u(*codepoints: int) -> str:
    """Spell non-ASCII test data by code point (the repository forbids Cyrillic text)."""
    return "".join(map(chr, codepoints))


NOVOSTI_RAIONA = u(
    0x41D, 0x43E, 0x432, 0x43E, 0x441, 0x442, 0x438, 0x20, 0x440, 0x430, 0x439, 0x43E, 0x43D, 0x430
)
OBYAVLENIYA = u(
    0x41E,
    0x431,
    0x44A,
    0x44F,
    0x432,
    0x43B,
    0x435,
    0x43D,
    0x438,
    0x44F,
    0x20,
    0x41C,
    0x43E,
    0x43D,
    0x442,
    0x435,
    0x432,
    0x438,
    0x434,
    0x435,
    0x43E,
)
SCHUKA = u(0x429, 0x443, 0x43A, 0x430, 0x20, 0x438, 0x20, 0x451, 0x436)
UKRAINIAN = u(
    0x407,
    0x436,
    0x430,
    0x20,
    0x404,
    0x432,
    0x430,
    0x20,
    0x490,
    0x430,
    0x43D,
    0x43E,
    0x43A,
    0x20,
    0x456,
)
CAFE_NFC = u(0x43, 0x61, 0x66, 0xE9, 0x20, 0x45, 0x73, 0x70, 0x61, 0xF1, 0x61)
CAFE_NFD = unicodedata.normalize("NFD", CAFE_NFC)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (NOVOSTI_RAIONA, "novosti_raiona"),
        (OBYAVLENIYA, "obyavleniya_montevideo"),
        (SCHUKA, "shchuka_i_yozh"),
        (UKRAINIAN, "yizha_yeva_ganok_i"),
        (u(0x53, 0x74, 0x72, 0x61, 0xDF, 0x65), "strasse"),
        (u(0x141, 0xF3, 0x64, 0x17A), "lodz"),
        (
            u(0xD8, 0x72, 0x65, 0x20, 0xC6, 0x62, 0x6C, 0x65, 0x20, 0x152, 0x75, 0x76, 0x72, 0x65),
            "ore_aeble_oeuvre",
        ),
        (u(0x45, 0x73, 0x70, 0x61, 0xF1, 0x61, 0x20, 0xBF, 0x51, 0x75, 0xE9, 0x3F), "espana_que"),
        (CAFE_NFD, "cafe_espana"),
        ("\U0001f525\U0001f525", "chat"),
    ],
)
def test_slugify_transliterates_cyrillic_and_european_letters(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_two_different_cyrillic_titles_get_different_folders() -> None:
    first = chat_folder_name(NOVOSTI_RAIONA, -1001)
    second = chat_folder_name(OBYAVLENIYA, -1002)
    assert first == "novosti_raiona_-1001"
    assert second == "obyavleniya_montevideo_-1002"


def test_transliterate_keeps_ascii_and_capitalises_upper_case_letters() -> None:
    assert transliterate("Plain ASCII 123") == "Plain ASCII 123"
    assert transliterate(u(0x416, 0x443, 0x43A)) == "Zhuk"
    assert transliterate(u(0x428, 0x428)) == "ShSh"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (CAFE_NFC, CAFE_NFD),
        (
            u(0x41D, 0x41E, 0x412, 0x41E, 0x421, 0x422, 0x418),
            u(0x43D, 0x43E, 0x432, 0x43E, 0x441, 0x442, 0x438),
        ),
        ("  Many \t  spaces\n", "many spaces"),
        (u(0x53, 0x74, 0x72, 0x61, 0xDF, 0x65), "STRASSE"),
    ],
)
def test_fold_makes_equal_what_a_person_considers_equal(left: str, right: str) -> None:
    assert fold(left) == fold(right)


def test_fold_keeps_different_words_apart() -> None:
    assert fold("Cafe") != fold(CAFE_NFC.split()[0])
    assert fold("a b") != fold("ab")
