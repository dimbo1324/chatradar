from __future__ import annotations

import importlib.metadata
import importlib.util
import io
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from chatimport import cli


@pytest.fixture
def invoked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(cli, "app", lambda: calls.append("app"))
    return calls


def test_run_switches_cp1252_streams_to_utf8_so_rich_help_cannot_crash(
    monkeypatch: pytest.MonkeyPatch, invoked: list[str]
) -> None:
    sink = io.BytesIO()
    out = io.TextIOWrapper(sink, encoding="cp1252")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    cli.run()

    assert out.encoding == "utf-8"
    assert err.encoding == "utf-8"
    out.write("\u2014 \u00b7 \u2026")
    out.flush()
    assert sink.getvalue() == "\u2014 \u00b7 \u2026".encode()
    assert invoked == ["app"]
    monkeypatch.undo()
    out.detach()
    err.detach()


def test_run_keeps_utf8_streams_untouched(
    monkeypatch: pytest.MonkeyPatch, invoked: list[str]
) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    reconfigured: list[str] = []

    def spy(**kwargs: Any) -> None:
        reconfigured.append("x")

    monkeypatch.setattr(out, "reconfigure", spy, raising=False)

    cli.run()

    assert reconfigured == []
    monkeypatch.undo()
    out.detach()


def test_run_ignores_streams_that_are_not_text_wrappers(
    monkeypatch: pytest.MonkeyPatch, invoked: list[str]
) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", None)

    cli.run()

    assert invoked == ["app"]


def test_run_still_calls_the_app_when_a_stream_is_already_utf8_in_any_case(
    monkeypatch: pytest.MonkeyPatch, invoked: list[str]
) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding="UTF-8")
    monkeypatch.setattr(sys, "stdout", out)

    cli.run()

    assert invoked == ["app"]
    monkeypatch.undo()
    out.detach()


def test_python_dash_m_chatimport_runs_the_cli_entry_point(
    monkeypatch: pytest.MonkeyPatch, invoked: list[str]
) -> None:
    runpy.run_module("chatimport.__main__", run_name="__main__")

    assert invoked == ["app"]


def test_the_version_falls_back_when_the_package_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    source = Path(cli.__file__).with_name("__init__.py")
    spec = importlib.util.spec_from_file_location("chatimport_init_copy", source)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__version__ == "0.0.0"


def test_the_version_comes_from_the_installed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def installed(name: str) -> str:
        return f"9.9.9+{name}"

    monkeypatch.setattr(importlib.metadata, "version", installed)
    source = Path(cli.__file__).with_name("__init__.py")
    spec = importlib.util.spec_from_file_location("chatimport_init_copy", source)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__version__ == "9.9.9+chatimport"
