"""Static panel assets: CSS, icon sprite, fonts and JS agree with each other."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from chatradar.web.app import STATIC_DIR

if TYPE_CHECKING:
    from pathlib import Path

CSS_FILES = sorted((STATIC_DIR / "css").glob("*.css"))
JS_FILES = sorted((STATIC_DIR / "js").rglob("*.js"))
SPRITE = STATIC_DIR / "icons" / "sprite.svg"
URL_REF = re.compile(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)")
IMPORT_REF = re.compile(r"""@import\s+(?:url\()?\s*["']?([^"')\s;]+)""")
ICON_PATTERNS = (
    re.compile(r"""\bicon\(\s*["']([\w-]+)["']"""),
    re.compile(r"""\biconButton\(\s*["']([\w-]+)["']"""),
    re.compile(r"""\bicon(?:Name)?:\s*["']([\w-]+)["']"""),
    re.compile(r"""\billus(?:tration)?[:(]\s*["']([\w-]+)["']"""),
    re.compile(r"""\bbadge\(.*["'][\w-]*["'],\s*["']([\w-]+)["']\)"""),
)
ICON_MAP = re.compile(r"\b(?:THEME_ICON|STAGE_ICONS|STATUS_ICON)\s*=\s*\{([^}]*)\}")


def _sprite_ids() -> set[str]:
    return set(re.findall(r'<symbol id="([\w-]+)"', SPRITE.read_text(encoding="utf-8")))


def _icons_used() -> set[str]:
    names: set[str] = set()
    for path in JS_FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in ICON_PATTERNS:
            names.update(pattern.findall(text))
        for block in ICON_MAP.findall(text):
            names.update(re.findall(r""":\s*["']([\w-]+)["']""", block))
    return names


def test_sprite_defines_the_icon_set() -> None:
    ids = _sprite_ids()

    assert len(ids) >= 25
    assert {"chats", "sun", "moon", "auto", "menu", "close", "undo", "tag", "book", "gauge"} <= ids
    text = SPRITE.read_text(encoding="utf-8")
    assert "http" not in text.replace("http://www.w3.org/2000/svg", "")
    assert "<style" not in text


def test_every_icon_used_in_js_exists_in_the_sprite() -> None:
    used = _icons_used()

    assert len(used) >= 20, "the icon extraction regexes are broken"
    assert sorted(used - _sprite_ids()) == []


@pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
def test_css_has_no_external_resources(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    assert "http://" not in text
    assert "https://" not in text
    assert "//" not in re.sub(r"/\*.*?\*/", "", "".join(URL_REF.findall(text)), flags=re.DOTALL)
    for target in IMPORT_REF.findall(text):
        assert target.startswith("./"), f"{path.name} imports a non-local stylesheet {target}"
        assert (path.parent / target).is_file()


def test_every_url_in_css_points_to_an_existing_static_file() -> None:
    urls = [url for path in CSS_FILES for url in URL_REF.findall(path.read_text(encoding="utf-8"))]

    assert urls, "no url() references found: the extraction regex is broken"
    for url in urls:
        assert url.startswith("/static/"), url
        assert (STATIC_DIR / url.removeprefix("/static/")).is_file(), url


def test_css_entry_imports_every_stylesheet() -> None:
    entry = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    imported = {target.removeprefix("./") for target in IMPORT_REF.findall(entry)}

    assert imported == {path.name for path in CSS_FILES if path.name != "app.css"}


def test_fonts_use_swap_and_unicode_range() -> None:
    text = (STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8")
    faces = re.findall(r"@font-face\s*\{[^}]*\}", text)

    assert len(faces) == 3
    for face in faces:
        assert "font-display: swap" in face
        assert "unicode-range" in face


def test_css_declares_both_themes_and_reduced_motion() -> None:
    tokens = (STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8")
    base = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")

    assert "prefers-color-scheme: dark" in tokens
    assert '[data-theme="dark"]' in tokens
    assert '[data-theme="light"]' in tokens
    assert "prefers-reduced-motion: reduce" in base
    assert ":focus-visible" in base


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.relative_to(STATIC_DIR).as_posix())
def test_js_has_no_inline_style_text_or_cyrillic(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    assert not re.search("[\u0400-\u04ff]", text), "UI text belongs in i18n/ru.json"
    assert "cssText" not in text
    assert not re.search(r"""setAttribute\(\s*["']style["']""", text)


def test_every_post_sends_the_csrf_header() -> None:
    api = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")

    assert '"X-Requested-With": "chatradar"' in api
    assert api.count('method: "POST"') == 1
    for path in JS_FILES:
        if path.name != "api.js":
            assert "method:" not in path.read_text(encoding="utf-8"), path.name
