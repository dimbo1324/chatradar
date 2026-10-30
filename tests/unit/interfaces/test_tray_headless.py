# pyright: reportPrivateUsage=false
"""A machine without a usable pystray (headless Linux) must still import the tray module."""

from __future__ import annotations

import builtins
import sys
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import tray
from chatimport.ports import ChatImportError

if TYPE_CHECKING:
    from tests.unit.interfaces.conftest import Env


def test_a_pystray_that_cannot_be_imported_means_no_tray(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pystray", None)

    assert tray._load_pystray() is None


def test_a_pystray_that_raises_something_else_on_import_means_no_tray(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pystray":
            raise RuntimeError("no display")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pystray", raising=False)
    monkeypatch.setattr(builtins, "__import__", failing_import)

    assert tray._load_pystray() is None


def test_a_usable_pystray_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setitem(sys.modules, "pystray", sentinel)

    assert tray._load_pystray() is sentinel


def test_creating_the_tray_without_pystray_is_a_clear_error(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tray, "pystray", None)

    with pytest.raises(ChatImportError, match="system tray"):
        tray._Tray(env.ctx)
