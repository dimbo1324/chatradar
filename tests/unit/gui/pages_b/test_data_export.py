from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog

from chatimport.gui.pages import data_export
from chatimport.usage import ArchiveUsage
from tests.unit.gui.pages_b.archive import ALPHA_ID

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from chatimport.gui.pages.data import DataPage
    from tests.unit.gui.pages_b.conftest import Opened, Toasts

type Settle = Callable[[Callable[[], bool]], None]


def loaded(page: DataPage, settle: Settle) -> None:
    page.calculate()
    settle(lambda: page.env.usage is not None and not page._calculating)  # pyright: ignore[reportPrivateUsage]


def exported(page: DataPage, settle: Settle) -> None:
    page.export.export()
    settle(lambda: not page.export._busy)  # pyright: ignore[reportPrivateUsage]


def pick(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_a: value))


def test_export_without_chats_does_nothing(data_page: DataPage, toasts: Toasts) -> None:
    card = data_page.export
    card.export()
    assert toasts.items == []
    data_page.env.set_usage(ArchiveUsage((), 0, 0, 0, None))
    data_page.show()
    assert card.empty.isVisibleTo(data_page)
    assert not card.run_button.isEnabled()


def test_export_default_destination(
    data_page: DataPage, settle: Settle, toasts: Toasts, opened: Opened
) -> None:
    card = data_page.export
    loaded(data_page, settle)
    assert card.run_button.isEnabled()
    card.chat.setCurrentIndex(card.chat.findData(ALPHA_ID))
    data_page.show()
    exported(data_page, settle)
    assert toasts.tones() == ["success"]
    assert card.done_row.isVisibleTo(data_page)
    out = next((data_page.env.root / "_exports").glob("*.json"))
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert len(rows) == 4
    card.open_button.click()
    assert opened.urls == [str(out.parent)]
    card.retranslate()


def test_export_to_chosen_folder_with_names(
    data_page: DataPage, settle: Settle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = data_page.export
    loaded(data_page, settle)
    target = tmp_path / "out"
    target.mkdir()
    pick(monkeypatch, str(target))
    card.browse.click()
    assert card._destination == target  # pyright: ignore[reportPrivateUsage]
    card.names.set_checked(True)
    exported(data_page, settle)
    assert list(target.glob("*.json"))
    pick(monkeypatch, "")
    card.browse.click()
    assert card._destination == target  # pyright: ignore[reportPrivateUsage]
    card.reset.click()
    assert card._destination is None  # pyright: ignore[reportPrivateUsage]


def test_export_failure(
    data_page: DataPage, settle: Settle, toasts: Toasts, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded(data_page, settle)

    def boom(*_a: object, **_k: object) -> Path:
        raise OSError("disk")

    monkeypatch.setattr(data_export, "export_chat_json", boom)
    exported(data_page, settle)
    assert toasts.tones() == ["danger"]


def test_export_folder_vanished(
    data_page: DataPage, settle: Settle, toasts: Toasts, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded(data_page, settle)

    def nothing(*_args: object) -> None:
        return None

    monkeypatch.setattr(data_export, "find_chat_folder", nothing)
    exported(data_page, settle)
    assert toasts.tones() == ["warning"]


def test_export_busy_and_open_without_result(data_page: DataPage, settle: Settle) -> None:
    card = data_page.export
    loaded(data_page, settle)
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    card.export()
    card._busy = False  # pyright: ignore[reportPrivateUsage]
    card._open()  # pyright: ignore[reportPrivateUsage]
    card.names.toggled.emit(True)
    assert not card.names_warning.isHidden()
