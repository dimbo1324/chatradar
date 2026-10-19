"""The Russian UI text lives in `static/i18n/ru.json`; these tests keep it complete and tidy."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, cast

import pytest

from chatradar.domain.lexicon import LexiconKind, TermSource, TermStatus
from chatradar.domain.models import MediaType, Source
from chatradar.pipeline import noise
from chatradar.pipeline.base import STAGE_ORDER
from chatradar.web.app import STATIC_DIR

if TYPE_CHECKING:
    from tests.unit.web.conftest import Panel

LOCALE = STATIC_DIR / "i18n" / "ru.json"
JS_FILES = sorted((STATIC_DIR / "js").rglob("*.js"))
KEY_CALL = re.compile(r"""\b(?:t|tn)\(\s*["']([\w.]+)["']""")
ENUM_CALL = re.compile(r"""\btEnum\(\s*["']([\w]+)["']""")
LABEL = re.compile(r"""\blabel:\s*["']([\w.]+)["']""")
PLURAL_FORMS = {"one", "few", "many", "other"}
CYRILLIC = re.compile("[\u0400-\u04ff]")


type Locale = dict[str, str | dict[str, str]]


def _messages() -> Locale:
    return cast("Locale", json.loads(LOCALE.read_text(encoding="utf-8")))


def _used() -> tuple[set[str], set[str]]:
    keys: set[str] = set()
    prefixes: set[str] = set()
    for path in JS_FILES:
        text = path.read_text(encoding="utf-8")
        keys.update(KEY_CALL.findall(text))
        keys.update(key for key in LABEL.findall(text) if "." in key)
        prefixes.update(ENUM_CALL.findall(text))
    return keys, prefixes


def test_locale_is_valid_json_with_text_values() -> None:
    for key, value in _messages().items():
        assert isinstance(value, str | dict), key
        if isinstance(value, dict):
            assert set(value) == PLURAL_FORMS, f"{key} needs one/few/many/other"
            assert all(isinstance(form, str) and form for form in value.values())


def test_every_key_used_by_the_code_exists() -> None:
    keys, prefixes = _used()
    messages = _messages()

    assert keys, "no t() calls found: the extraction regex is broken"
    assert sorted(key for key in keys if key not in messages) == []
    for prefix in prefixes:
        assert any(k.startswith(f"{prefix}.") for k in messages), f"no keys for tEnum({prefix})"


def test_no_unused_keys() -> None:
    keys, prefixes = _used()
    unused = [
        key
        for key in _messages()
        if key not in keys and key.partition(".")[0] not in prefixes and key != "app.name"
    ]

    assert unused == []


def test_plural_keys_are_used_with_tn_and_plain_keys_with_t() -> None:
    messages = _messages()
    for path in JS_FILES:
        text = path.read_text(encoding="utf-8")
        for key in re.findall(r"""\btn\(\s*["']([\w.]+)["']""", text):
            assert isinstance(messages[key], dict), f"{key} used with tn() must have plural forms"
        for key in re.findall(r"""\bt\(\s*["']([\w.]+)["']""", text):
            assert isinstance(messages[key], str), f"{key} used with t() must be a plain string"


def test_placeholders_match_between_plural_forms() -> None:
    for key, value in _messages().items():
        if isinstance(value, dict):
            names = {frozenset(re.findall(r"\{(\w+)\}", form)) for form in value.values()}
            assert len(names) == 1, f"{key}: forms use different placeholders"


def test_backend_values_are_translated() -> None:
    messages = _messages()
    reasons = [v for k, v in vars(noise).items() if k.startswith("REASON_")]
    expected = (
        [f"noise_reason.{reason}" for reason in reasons]
        + [f"stage.{stage}" for stage in STAGE_ORDER]
        + [f"media.{media.value}" for media in MediaType]
        + [f"source.{source.value}" for source in Source]
        + [f"lang.{lang}" for lang in ("ru", "es", "en", "mixed", "unknown", "any")]
        + [f"lexicon_kind.{kind.value}" for kind in LexiconKind]
        + [f"term_status.{status.value}" for status in TermStatus]
        + [f"term_source.{source.value}" for source in TermSource]
        + [f"lexicon_order.{order}" for order in ("score", "occurrences", "recent")]
        + [f"eval_source.{source}" for source in ("human-labels", "truth-file")]
    )

    assert reasons
    assert [key for key in expected if key not in messages] == []


def test_ui_text_is_russian() -> None:
    messages = _messages()
    plain = [v for v in messages.values() if isinstance(v, str)]
    forms = [f for v in messages.values() if isinstance(v, dict) for f in v.values()]
    brand_or_empty = {
        "media.none",
        "common.telegram_link",
        "common.utc",
    }  # no text, a brand, an abbreviation
    for key, value in messages.items():
        flat = [value] if isinstance(value, str) else list(value.values())
        if key in brand_or_empty or key.startswith("source."):
            continue
        assert any(CYRILLIC.search(text) for text in flat), f"{key} is not translated"
    assert len(plain) + len(forms) > 100


@pytest.mark.parametrize("path", ["/static/i18n/ru.json", "/static/js/i18n.js"])
def test_locale_assets_are_served(panel: Panel, path: str) -> None:
    response = panel.client.get(path)

    assert response.status_code == 200
    if path.endswith(".json"):
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["app.name"]


def test_index_is_russian_and_has_no_hardcoded_menu() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert '<html lang="ru">' in html
    assert "<li>" not in html  # the menu is built from the routes with translated labels
