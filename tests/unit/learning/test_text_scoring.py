from __future__ import annotations

import math

import pytest

from chatradar.learning.contact_words import has_contact_word, is_contact_token
from chatradar.learning.scoring import log_odds_z
from chatradar.learning.text import (
    is_safe_term,
    is_unsafe_text,
    leading_tokens,
    message_ngrams,
    ngrams,
    segments,
)


def test_segments_fold_and_cut_at_unsafe_tokens() -> None:
    text = "Write me in DM @easy_money_demo asap, tel +59899123456 or https://x.example/a"

    assert segments(text) == [["write", "me", "in", "dm"], ["asap", "tel"], ["or"]]


def test_segments_of_plain_text_is_one_stretch() -> None:
    assert segments("¿Alguien sabe, dónde?") == [["alguien", "sabe", "donde"]]
    assert segments("   ") == []


def test_leading_tokens_stop_at_first_unsafe_token() -> None:
    assert leading_tokens("Who knows @bob how?") == ["who", "knows"]
    assert leading_tokens("@bob who knows") == []
    assert leading_tokens("Who knows how") == ["who", "knows", "how"]


def test_ngrams_are_distinct_and_ordered_by_text() -> None:
    assert ngrams(["a", "b", "a", "b"], 2) == {"a", "b", "a b", "b a"}
    assert ngrams(["a", "b", "c"], 3, min_n=2) == {"a b", "b c", "a b c"}
    assert ngrams([], 3) == set()


def test_message_ngrams_never_span_an_unsafe_token() -> None:
    found = message_ngrams("dm @bob money", 2)

    assert found == {"dm", "money"}  # "dm bob" and "bob money" would span the mention


@pytest.mark.parametrize(
    ("term", "safe"),
    [
        ("write me in dm", True),
        ("x", False),
        ("a@b", False),
        ("see http", False),
        ("call 099123456 now", False),
        ("call 12345 now", True),
        ("a" * 201, False),
    ],
)
def test_is_safe_term(term: str, safe: bool) -> None:
    assert is_safe_term(term) is safe


def test_is_unsafe_text() -> None:
    assert is_unsafe_text("see t.me/chat") is True
    assert is_unsafe_text("mail me@x.org") is True
    assert is_unsafe_text("thanks") is False


def test_contact_words_use_escaped_cyrillic() -> None:
    assert is_contact_token("\u043b\u0441")
    assert is_contact_token("\u043b\u0438\u0447\u043a\u0443")
    assert is_contact_token("privado")
    assert is_contact_token("dm")
    assert not is_contact_token("deal")
    assert has_contact_word("write to inbox now")
    assert not has_contact_word("easy money")


def test_log_odds_matches_the_hand_computed_value() -> None:
    # y_t=10, y_b=0, n_t=n_b=100, alpha_0=20: alpha_w = 20 * 10 / 200 = 1
    # delta = ln(11 / 109) - ln(1 / 119); var = 1/11 + 1/1
    expected = (math.log(11 / 109) - math.log(1 / 119)) / math.sqrt(1 / 11 + 1)

    z = log_odds_z(10, 0, 100, 100, prior_strength=20)

    assert z == pytest.approx(expected)
    assert z == pytest.approx(2.3797, abs=1e-3)


def test_log_odds_is_antisymmetric_and_zero_at_equal_rates() -> None:
    assert log_odds_z(10, 10, 100, 100) == pytest.approx(0.0)
    toward = log_odds_z(9, 1, 100, 100)
    away = log_odds_z(1, 9, 100, 100)

    assert toward > 0
    assert away == pytest.approx(-toward)


def test_log_odds_prior_shrinks_rare_terms() -> None:
    rare = log_odds_z(2, 0, 1000, 1000)
    common = log_odds_z(20, 0, 1000, 1000)

    assert 0 < rare < common


@pytest.mark.parametrize(("target", "total"), [(0, 100), (5, 0)])
def test_log_odds_of_nothing_is_zero(target: int, total: int) -> None:
    assert log_odds_z(target, 0, total, 100) == 0.0


def test_log_odds_prior_never_exceeds_half_of_a_small_corpus() -> None:
    # classes of 20 and 20 items: alpha_0 = min(500, 40 / 2) = 20
    assert log_odds_z(8, 0, 20, 20) == pytest.approx(log_odds_z(8, 0, 20, 20, prior_strength=20))
    assert log_odds_z(8, 0, 2000, 2000) == pytest.approx(
        log_odds_z(8, 0, 2000, 2000, prior_strength=500)
    )
