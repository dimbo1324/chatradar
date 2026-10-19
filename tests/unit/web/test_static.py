from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from chatradar.web.app import CONTENT_SECURITY_POLICY, STATIC_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from tests.unit.web.conftest import Panel

JS_FILES = sorted(STATIC_DIR.rglob("*.js"))
UNSAFE_SINKS = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b|\beval\(")
IMPORT_PATH = re.compile(r"""^\s*import\b[^"']*["']([^"']+)["']""", re.MULTILINE)
VIEWS = ("chats", "pipeline", "messages", "thread", "search", "review", "lexicon", "quality")


def test_index_is_served_with_a_strict_csp(panel: Panel) -> None:
    response = panel.client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert '<script type="module" src="/static/js/app.js">' in response.text


def test_csp_allows_only_self() -> None:
    assert "default-src 'self'" in CONTENT_SECURITY_POLICY
    assert "script-src 'self';" in CONTENT_SECURITY_POLICY
    assert "unsafe" not in CONTENT_SECURITY_POLICY
    assert "http" not in CONTENT_SECURITY_POLICY


def test_api_responses_carry_the_csp(panel: Panel) -> None:
    response = panel.client.get("/api/chats")

    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/index.html", "text/html"),
        ("/static/css/app.css", "text/css"),
        ("/static/js/app.js", "text/javascript"),
        ("/static/js/views/thread.js", "text/javascript"),
        ("/static/js/views/lexicon.js", "text/javascript"),
        ("/static/js/views/quality.js", "text/javascript"),
        ("/static/js/theme-init.js", "text/javascript"),
        ("/static/icons/sprite.svg", "image/svg+xml"),
        ("/static/icons/favicon.svg", "image/svg+xml"),
    ],
)
def test_assets_have_correct_content_types(panel: Panel, path: str, content_type: str) -> None:
    response = panel.client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_missing_asset_is_404(panel: Panel) -> None:
    assert panel.client.get("/static/js/missing.js").status_code == 404


def test_every_view_has_a_module() -> None:
    for view in VIEWS:
        assert (STATIC_DIR / "js" / "views" / f"{view}.js").is_file()


def test_index_uses_no_external_resources() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "http://" not in html
    assert "https://" not in html
    assert "<style" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.relative_to(STATIC_DIR).as_posix())
def test_js_uses_no_html_sinks(path: Path) -> None:
    assert not UNSAFE_SINKS.search(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.relative_to(STATIC_DIR).as_posix())
def test_js_imports_resolve(path: Path) -> None:
    for target in IMPORT_PATH.findall(path.read_text(encoding="utf-8")):
        assert target.startswith("."), f"{path.name} imports a non-local module {target}"
        assert (path.parent / target).resolve().is_file(), f"{path.name}: {target} missing"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.relative_to(STATIC_DIR).as_posix())
def test_js_parses_as_a_module(path: Path, tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node is not None
    module = tmp_path / f"{path.stem}.mjs"  # .mjs forces module parsing on every node version
    module.write_bytes(path.read_bytes())

    result = subprocess.run(  # noqa: S603 - fixed executable, a copied repository file
        [node, "--check", str(module)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["cyrillic", "latin", "latin-ext"])
def test_fonts_are_served(panel: Panel, name: str) -> None:
    response = panel.client.get(f"/static/fonts/inter-{name}-wght-normal.woff2")

    assert response.status_code == 200
    assert response.content[:4] == b"wOF2"
    # Starlette takes the type from the platform's mimetypes table, which lacks .woff2 on some
    # systems (Windows); browsers load fonts regardless of the type, nosniff does not apply.
    served_type = response.headers["content-type"].split(";")[0]
    assert served_type in {"font/woff2", "application/octet-stream"}
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
