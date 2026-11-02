from __future__ import annotations

import pytest

from chatimport.search_fold import clean_text, search_key
from tests.unit.storage.helpers import chars

E_ACUTE = chars(0xE9)
E_CIRCUMFLEX = chars(0xEA)
E_GRAVE = chars(0xE8)
SHARP_S = chars(0xDF)
COMBINING_ACUTE = chars(0x301)
COMBINING_BREVE = chars(0x306)
YO_UPPER = chars(0x401)
YO_LOWER = chars(0x451)
YE_LOWER = chars(0x435)
ZHE_LOWER = chars(0x436)
SHORT_I = chars(0x439)
PLAIN_I = chars(0x438)
RU_UPPER_WORD = chars(0x41F, 0x420, 0x418, 0x412, 0x415, 0x422)
RU_LOWER_WORD = chars(0x43F, 0x440, 0x438, 0x432, 0x435, 0x442)


def test_case_is_ignored() -> None:
    assert search_key("HeLLo WORLD") == "hello world"
    assert search_key(RU_UPPER_WORD) == RU_LOWER_WORD


def test_sharp_s_folds_like_casefold() -> None:
    assert search_key(f"Stra{SHARP_S}e") == "strasse"


@pytest.mark.parametrize(
    "text",
    [
        f"Caf{E_ACUTE}",
        f"cafe{COMBINING_ACUTE}",
        f"CAF{E_ACUTE.upper()}",
        f"caf{E_CIRCUMFLEX}",
        f"caf{E_GRAVE}",
        "cafe",
    ],
)
def test_latin_accents_are_dropped(text: str) -> None:
    assert search_key(text) == "cafe"


def test_yo_is_the_same_as_ye() -> None:
    assert search_key(YO_UPPER + ZHE_LOWER) == YE_LOWER + ZHE_LOWER
    assert search_key(YO_LOWER) == YE_LOWER


def test_short_i_stays_distinct_from_plain_i() -> None:
    assert search_key(SHORT_I) == SHORT_I
    assert search_key(SHORT_I) != search_key(PLAIN_I)
    assert search_key(PLAIN_I + COMBINING_BREVE) == SHORT_I


def test_a_mark_without_a_base_letter_is_dropped() -> None:
    assert search_key(COMBINING_ACUTE + "a") == "a"


def test_white_space_is_collapsed_and_trimmed() -> None:
    assert search_key("  a \n\t b  ") == "a b"
    assert search_key(" \n ") == ""


def test_clean_text_drops_nul_and_replaces_lone_surrogates() -> None:
    assert clean_text("a\x00b") == "ab"
    assert clean_text("a" + chr(0xD800) + "b") == "a?b"
    assert clean_text("plain") == "plain"
    assert search_key("x" + chr(0xD800) + "y") == "x?y"
