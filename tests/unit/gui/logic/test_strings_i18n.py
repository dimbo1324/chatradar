from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, cast

import pytest

from chatimport.gui import i18n, strings
from chatimport.gui.i18n import LanguageManager, plural, tr
from chatimport.gui.strings import (
    LocaleDriftError,
    _placeholders,  # pyright: ignore[reportPrivateUsage]
    _validate,  # pyright: ignore[reportPrivateUsage]
    check_drift,
    has_key,
    plural_index,
    register_strings,
    translate,
    translate_plural,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

LOCALE_MODULES = ("chats", "data", "log", "overview", "placeholder", "settings", "shell")


@pytest.fixture(autouse=True)
def english() -> Iterator[None]:
    strings.set_current_language("en")
    yield
    strings.set_current_language("en")


@pytest.fixture
def clean_catalogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strings, "_catalogs", {"en": {}, "ru": {}})


@pytest.mark.parametrize(
    ("n", "en", "ru"),
    [
        (0, 1, 2),
        (1, 0, 0),
        (2, 1, 1),
        (4, 1, 1),
        (5, 1, 2),
        (11, 1, 2),
        (12, 1, 2),
        (14, 1, 2),
        (21, 1, 0),
        (22, 1, 1),
        (25, 1, 2),
        (101, 1, 0),
        (111, 1, 2),
        (-1, 0, 0),
        (-3, 1, 1),
    ],
)
def test_plural_index(n: int, en: int, ru: int) -> None:
    assert plural_index("en", n) == en
    assert plural_index("ru", n) == ru


def test_placeholders_of_text_and_plural_entry() -> None:
    assert _placeholders("{a} and {b}") == {"a", "b"}
    assert _placeholders(("{n} one", "{n} many {x}")) == {"n", "x"}


def test_translate_fills_known_params_and_keeps_unknown_ones() -> None:
    assert translate("en", "nav.soon_hint", page="Log") == "Log".join(
        ("", " arrives in a later version of the window.")
    )
    assert translate("en", "nav.soon_hint") == "{page} arrives in a later version of the window."


def test_translate_missing_key_returns_the_key() -> None:
    assert translate("en", "no.such.key") == "no.such.key"
    assert translate_plural("ru", 3, "no.such.key") == "no.such.key"


def test_translate_of_a_plural_entry_uses_the_last_form() -> None:
    assert translate("en", "count.chats", n=7) == "7 chats"


def test_translate_plural_forms() -> None:
    assert translate_plural("en", 1, "count.chats") == "1 chat"
    assert translate_plural("en", 3, "count.chats") == "3 chats"
    assert translate_plural("en", 1, "app.title") == "ChatImport"
    forms = {translate_plural("ru", n, "count.chats") for n in (1, 2, 5)}
    assert len(forms) == 3


def test_has_key() -> None:
    assert has_key("app.title")
    assert not has_key("app.nope")


def test_register_adds_prefixed_and_bare_keys(clean_catalogs: None) -> None:
    register_strings(
        "ns", {"a": "A", "p": ("{n} x", "{n} xs")}, {"a": "B", "p": ("{n}", "{n}", "{n}")}
    )
    register_strings("", {"bare": "x"}, {"bare": "y"})
    assert translate("en", "ns.a") == "A"
    assert translate("ru", "ns.a") == "B"
    assert translate("en", "bare") == "x"


def test_register_rejects_a_duplicate_key(clean_catalogs: None) -> None:
    register_strings("ns", {"a": "A"}, {"a": "B"})
    with pytest.raises(LocaleDriftError, match="duplicate"):
        register_strings("ns", {"a": "A"}, {"a": "B"})


@pytest.mark.parametrize(
    ("en", "ru", "fragment"),
    [
        ({"a": "x"}, {}, "missing in ru: a"),
        ({}, {"a": "x"}, "missing in en: a"),
        ({"a": ("1", "2")}, {"a": "x"}, "plural shape differs"),
        ({"a": "{x}"}, {"a": "{y}"}, "placeholders differ"),
        ({"a": ("1",)}, {"a": ("{n}", "{n}", "{n}")}, "en plural a needs 2 forms"),
        ({"a": ("1", "2")}, {"a": ("1", "2")}, "ru plural a needs 3 forms"),
    ],
)
def test_validate_reports_each_kind_of_drift(
    en: dict[str, Any], ru: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(LocaleDriftError, match=fragment):
        _validate("ns", en, ru)


def test_check_drift_passes_on_the_merged_catalogues() -> None:
    check_drift()


def test_ensure_core_loads_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strings, "_core_loaded", False)
    monkeypatch.setattr(strings, "_catalogs", {"en": {}, "ru": {}})
    assert has_key("app.title")
    assert has_key("app.title")


def test_tr_and_plural_follow_the_current_language() -> None:
    assert tr("nav.chats") == "Chats"
    assert plural(1, "count.chats") == "1 chat"
    strings.set_current_language("ru")
    assert tr("nav.chats") == translate("ru", "nav.chats")
    assert plural(5, "count.chats") == translate_plural("ru", 5, "count.chats")


def test_language_manager_switches_and_signals(qapp: object) -> None:
    manager = LanguageManager("en")
    seen: list[str] = []
    manager.changed.connect(seen.append)
    assert manager.current == "en"
    manager.set_language("en")
    manager.set_language("de")  # type: ignore[arg-type]
    assert seen == []
    manager.set_language("ru")
    assert manager.current == "ru"
    assert seen == ["ru"]


def test_i18n_reexports() -> None:
    for name in i18n.__all__:
        assert hasattr(i18n, name)


def _tables(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    module = importlib.import_module(f"chatimport.gui.locales.{name}")
    return module.EN, module.RU


@pytest.mark.parametrize("name", LOCALE_MODULES)
def test_locale_module_tables_agree(name: str) -> None:
    en, ru = _tables(name)
    assert en
    assert en.keys() == ru.keys()
    _validate(name, en, ru)
    for key in en:
        entry = cast("str | tuple[str, ...]", en[key])
        ru_entry = cast("str | tuple[str, ...]", ru[key])
        if isinstance(entry, tuple):
            assert len(entry) == 2, key
            assert len(ru_entry) == 3, key
        assert _placeholders(entry) == _placeholders(ru_entry), key


def test_core_locale_tables_agree() -> None:
    from chatimport.gui.locales import en, ru

    _validate("core", en.EN, ru.RU)
    assert en.EN.keys() == ru.RU.keys()
    plurals = [key for key, entry in en.EN.items() if isinstance(entry, tuple)]
    assert plurals
    for key in plurals:
        assert len(en.EN[key]) == 2
        assert len(ru.RU[key]) == 3


def test_every_locale_module_registers_without_drift() -> None:
    for name in LOCALE_MODULES:
        importlib.import_module(f"chatimport.gui.locales.{name}")
    check_drift()
