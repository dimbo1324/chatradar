from __future__ import annotations

from itertools import pairwise

import pytest

from chatimport.gui.models.search_spans import (
    ELLIPSIS,
    Snippet,
    find_spans,
    fold_needle,
    highlight_html,
    snippet,
)

YO_CAPITAL = "\u0401"
YO = "\u0451"
YE = "\u0435"
ZH = "\u0436"
I_SHORT = "\u0439"
CYR_I = "\u0438"
SHARP_S = "ß"
ACUTE = "́"


@pytest.mark.parametrize(
    ("text", "needle", "expected"),
    [
        ("Hello World", "world", [(6, 11)]),
        ("Hello World", "WORLD", [(6, 11)]),
        ("abcabc", "bc", [(1, 3), (4, 6)]),
        ("aaaa", "aa", [(0, 4)]),
        ("abab", "ab", [(0, 4)]),
        ("abc", "zz", []),
        ("", "a", []),
        ("abc", "", []),
        ("abc", "   ", []),
        ("a   b", "a b", [(0, 5)]),
        ("a \n b", "a b", [(0, 5)]),
        ("xx a yy", " a ", [(3, 4)]),
        (" a", "a", [(1, 2)]),
        ("\u041f\u0440\u0418\u0412\u0435\u0422", "\u043f\u0440\u0438\u0432\u0435\u0442", [(0, 6)]),
    ],
)
def test_plain_matches(text: str, needle: str, expected: list[tuple[int, int]]) -> None:
    assert find_spans(text, needle) == expected


@pytest.mark.parametrize(
    ("text", "needle", "expected"),
    [
        (f"Stra{SHARP_S}e", "strasse", [(0, 6)]),
        (f"Stra{SHARP_S}e", "ss", [(4, 5)]),
        (f"a{SHARP_S}b", "s", [(1, 2)]),
        (f"a{SHARP_S}b", "b", [(2, 3)]),
        (f"cafe{ACUTE}", "cafe", [(0, 5)]),
        ("café", "cafe", [(0, 4)]),
        (f"CAFE{ACUTE}", "café", [(0, 5)]),
        (f"e{ACUTE}x", "x", [(2, 3)]),
        (f"{ACUTE}a", "a", [(1, 2)]),
        (f"{YO_CAPITAL}{ZH}\u0438\u043a", f"{YE}{ZH}", [(0, 2)]),
        (f"{YE}{ZH}\u0438\u043a", f"{YO}{ZH}", [(0, 2)]),
        (f"{I_SHORT}", f"{CYR_I}", []),
        (f"{CYR_I}", f"{I_SHORT}", []),
        (f"{I_SHORT.upper()}\u043e\u0433\u0443\u0440\u0442", f"{I_SHORT}", [(0, 1)]),
        ("Ñandú", "nandu", [(0, 5)]),
    ],
)
def test_folding_keeps_spans_valid_for_the_original(
    text: str, needle: str, expected: list[tuple[int, int]]
) -> None:
    assert find_spans(text, needle) == expected


def test_spans_are_sorted_and_never_overlap() -> None:
    spans = find_spans("ababab xx abab", "ab")
    assert spans == sorted(spans)
    assert all(a[1] < b[0] for a, b in pairwise(spans))
    assert spans == [(0, 6), (10, 14)]


def test_every_span_folds_to_text_containing_the_needle() -> None:
    text = f"Stra{SHARP_S}e and café cafe{ACUTE} {YO_CAPITAL}{ZH} {YE}{ZH}"
    for needle in ("stra", "cafe", f"{YE}{ZH}", "e a"):
        for start, end in find_spans(text, needle):
            assert fold_needle(needle) in fold_needle(text[start:end])


def test_fold_needle() -> None:
    assert fold_needle("  Ab" + ACUTE + "C  d ") == "abc d"
    assert fold_needle("") == ""
    assert fold_needle(" \n ") == ""
    assert fold_needle(f"Stra{SHARP_S}e") == "strasse"


def test_short_text_is_returned_whole() -> None:
    assert snippet("hello world", "WORLD") == Snippet("hello world", ((6, 11),), False)


def test_snippet_flattens_line_breaks_one_to_one() -> None:
    result = snippet("a\nb\r\nc", "b")
    assert result.text == "a b  c"
    assert result.spans == ((2, 3),)
    assert not result.truncated


def test_long_text_is_cut_around_the_first_match_on_both_sides() -> None:
    long = "word " * 200 + "needle" + " tail" * 200
    result = snippet(long, "needle")
    assert result.truncated
    assert result.text.startswith(ELLIPSIS)
    assert result.text.endswith(ELLIPSIS)
    assert len(result.text) <= 322
    assert [result.text[a:b] for a, b in result.spans] == ["needle"]


def test_match_at_the_start_has_no_leading_ellipsis() -> None:
    result = snippet("needle " + "word " * 200, "needle")
    assert result.truncated
    assert result.text.startswith("needle")
    assert result.text.endswith(ELLIPSIS)
    assert result.spans == ((0, 6),)


def test_match_at_the_end_has_no_trailing_ellipsis() -> None:
    result = snippet("word " * 200 + "needle", "needle")
    assert result.truncated
    assert result.text.startswith(ELLIPSIS)
    assert result.text.endswith("needle")
    assert [result.text[a:b] for a, b in result.spans] == ["needle"]


def test_no_needle_keeps_the_start() -> None:
    result = snippet("word " * 200, "")
    assert result.truncated
    assert not result.text.startswith(ELLIPSIS)
    assert result.text.endswith(ELLIPSIS)
    assert result.spans == ()
    assert len(result.text) == 320


def test_text_without_spaces_is_cut_hard() -> None:
    result = snippet("x" * 1000 + "needle" + "y" * 1000, "needle")
    assert result.text[0] == ELLIPSIS
    assert result.text[-1] == ELLIPSIS
    assert [result.text[a:b] for a, b in result.spans] == ["needle"]


def test_a_span_cut_by_the_end_is_clipped() -> None:
    result = snippet("aaaa bbbb cccc dddd eeee", "bbbb cccc", limit=12)
    assert result == Snippet("aaaa bbbb" + ELLIPSIS, ((5, 9),), True)


def test_a_match_outside_the_window_is_dropped() -> None:
    result = snippet("aaaa bbbb cccc dddd eeee", "cccc dddd", limit=12)
    assert result.spans == ()
    assert result.text == "aaaa bbbb" + ELLIPSIS


def test_highlight_html_escapes_and_marks_spans() -> None:
    html = highlight_html("a<b>&\nc", [(0, 1), (2, 5)], "#fff")
    assert html == (
        '<span style="background-color:#fff">a</span>&lt;'
        '<span style="background-color:#fff">b&gt;&amp;</span><br>c'
    )


def test_highlight_html_without_spans() -> None:
    assert highlight_html("plain <x>", [], "#fff") == "plain &lt;x&gt;"
