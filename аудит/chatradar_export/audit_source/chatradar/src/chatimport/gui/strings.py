"""The string catalogue behind `i18n`: pure, Qt-free, importable from `format`.

Every page registers its own namespace with `register_strings`; the English and Russian tables
must carry the same keys, the same plural shape and the same placeholders, and a mismatch
raises `LocaleDriftError` at registration, so a missing translation fails on the first run
rather than showing up as a raw key in front of the owner.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

type Language = Literal["en", "ru"]
type Entry = str | tuple[str, ...]

LANGUAGES: Final[tuple[Language, ...]] = ("en", "ru")
PLURAL_FORMS: Final[Mapping[Language, int]] = {"en": 2, "ru": 3}

_PLACEHOLDER: Final = re.compile(r"\{(\w+)\}")

_catalogs: dict[Language, dict[str, Entry]] = {"en": {}, "ru": {}}
_core_loaded = False
_current: Language = "en"


class LocaleDriftError(ValueError):
    pass


def _placeholders(entry: Entry) -> set[str]:
    texts = (entry,) if isinstance(entry, str) else entry
    return {name for text in texts for name in _PLACEHOLDER.findall(text)}


def _tables(
    en: Mapping[str, Entry], ru: Mapping[str, Entry]
) -> tuple[tuple[Language, Mapping[str, Entry]], tuple[Language, Mapping[str, Entry]]]:
    return (("en", en), ("ru", ru))


def _validate(namespace: str, en: Mapping[str, Entry], ru: Mapping[str, Entry]) -> None:
    problems: list[str] = []
    problems += [f"missing in ru: {key}" for key in sorted(en.keys() - ru.keys())]
    problems += [f"missing in en: {key}" for key in sorted(ru.keys() - en.keys())]
    for key in sorted(en.keys() & ru.keys()):
        for language, table in _tables(en, ru):
            entry = table[key]
            if isinstance(entry, tuple) and len(entry) != PLURAL_FORMS[language]:
                problems.append(f"{language} plural {key} needs {PLURAL_FORMS[language]} forms")
        if isinstance(en[key], str) != isinstance(ru[key], str):
            problems.append(f"plural shape differs: {key}")
        elif _placeholders(en[key]) != _placeholders(ru[key]):
            problems.append(f"placeholders differ: {key}")
    if problems:
        listing = "; ".join(problems)
        raise LocaleDriftError(f"locale drift in namespace {namespace!r}: {listing}")


def register_strings(namespace: str, en: Mapping[str, Entry], ru: Mapping[str, Entry]) -> None:
    """Add `namespace.key` entries (an empty namespace adds bare keys, for the core table).

    A tuple value is a plural entry: two forms in English (one, other), three in Russian
    (one, few, many).
    """
    _validate(namespace, en, ru)
    prefix = f"{namespace}." if namespace else ""
    for language, table in _tables(en, ru):
        catalog = _catalogs[language]
        for key, entry in table.items():
            full = prefix + key
            if full in catalog:
                raise LocaleDriftError(f"duplicate string key {full!r}")
            catalog[full] = entry


def _ensure_core() -> None:
    global _core_loaded
    if _core_loaded:
        return
    _core_loaded = True
    from chatimport.gui.locales import en as core_en
    from chatimport.gui.locales import ru as core_ru

    register_strings("", core_en.EN, core_ru.RU)


def current_language() -> Language:
    return _current


def set_current_language(language: Language) -> None:
    global _current
    _current = language


def plural_index(language: Language, n: int) -> int:
    count = abs(n)
    if language == "en":
        return 0 if count == 1 else 1
    if count % 10 == 1 and count % 100 != 11:
        return 0
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return 1
    return 2


def _fill(template: str, params: Mapping[str, object]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), template)


def translate(language: Language, key: str, **params: object) -> str:
    _ensure_core()
    entry = _catalogs[language].get(key)
    if entry is None:
        return key
    text = entry if isinstance(entry, str) else entry[-1]
    return _fill(text, params)


def translate_plural(language: Language, count: int, key: str, **params: object) -> str:
    _ensure_core()
    entry = _catalogs[language].get(key)
    if entry is None:
        return key
    text = entry if isinstance(entry, str) else entry[plural_index(language, count)]
    return _fill(text, {"n": count, **params})


def has_key(key: str) -> bool:
    _ensure_core()
    return key in _catalogs["en"]


def check_drift() -> None:
    """Re-verify the merged catalogues; raises `LocaleDriftError` on any mismatch."""
    _ensure_core()
    _validate("<all>", _catalogs["en"], _catalogs["ru"])
