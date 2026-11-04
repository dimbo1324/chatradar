from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog

from chatimport.commands import CommandResult
from chatimport.gui.pages import data_folder, data_folder_dialog
from chatimport.gui.pages.data_folder_dialog import FolderDialog

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.gui.context import GuiContext
    from chatimport.gui.pages.data import DataPage
    from tests.unit.gui.conftest import FakeBridge
    from tests.unit.gui.pages_b.conftest import Answers, Clipboard, Opened, Toasts


def always(_path: object) -> bool:
    return True


def scripted_dialog(
    monkeypatch: pytest.MonkeyPatch, text: str, *, move: bool = True, accept: bool = True
) -> None:
    class Scripted(FolderDialog):
        def exec(self) -> int:
            self.path.setText(text)
            self.move_box.setChecked(move)
            self.validate()
            if accept:
                self.apply.click()
                return QDialog.DialogCode.Accepted
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(data_folder, "FolderDialog", Scripted)


def test_card_renders_root(
    data_page: DataPage, clipboard: Clipboard, opened: Opened, toasts: Toasts
) -> None:
    card = data_page.folder
    assert card.path_label.toolTip() == str(data_page.env.root)
    card.copy_button.click()
    assert clipboard.text == str(data_page.env.root)
    card.open_button.click()
    assert opened.urls == [str(data_page.env.root)]
    assert toasts.tones() == ["info"]


def test_cloud_and_missing_flags(
    data_page: DataPage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = data_page.folder
    data_page.show()
    monkeypatch.setattr(data_folder, "is_cloud_synced", always)
    data_page.env.set_root(tmp_path / "nowhere")
    assert card.missing.isVisibleTo(data_page)
    assert card.cloud.isVisibleTo(data_page)


def test_change_moves_data(
    data_page: DataPage,
    gui: GuiContext,
    bridge: FakeBridge,
    answers: Answers,
    toasts: Toasts,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new = tmp_path / "elsewhere" / "ChatImport"
    scripted_dialog(monkeypatch, str(new))
    bridge.replies["set_root"] = CommandResult(True, data={"path": str(new)})
    data_page.folder.change()
    assert bridge.calls == [("set_root", {"path": str(new), "move": True})]
    assert data_page.env.root == new
    assert toasts.tones() == ["success"]


def test_change_fresh_without_path_in_reply(
    data_page: DataPage,
    bridge: FakeBridge,
    answers: Answers,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = data_page.env.root
    scripted_dialog(monkeypatch, str(tmp_path / "fresh"), move=False)
    data_page.folder.change()
    assert bridge.calls[0][1]["move"] is False
    assert data_page.env.root == old


def test_change_rejected_or_declined(
    data_page: DataPage,
    bridge: FakeBridge,
    answers: Answers,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = data_page.folder
    scripted_dialog(monkeypatch, str(tmp_path / "x"), accept=False)
    card.change()
    scripted_dialog(monkeypatch, "")
    card.change()
    scripted_dialog(monkeypatch, str(tmp_path / "y"))
    answers.accept = False
    card.change()
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    card.change()
    assert bridge.calls == []


def test_change_failed_and_unavailable(
    data_page: DataPage,
    bridge: FakeBridge,
    answers: Answers,
    toasts: Toasts,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted_dialog(monkeypatch, str(tmp_path / "z"))
    bridge.replies["set_root"] = CommandResult(False, "no")
    data_page.folder.change()

    def execute(command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    bridge.execute = execute  # type: ignore[method-assign]
    data_page.folder.change()
    assert toasts.tones() == ["danger", "warning"]
    data_page.folder.retranslate()


@pytest.fixture
def dialog(gui: GuiContext, qapp: object, tmp_path: Path) -> FolderDialog:
    return FolderDialog(gui, gui.current.root)


def test_dialog_validates_on_commit(dialog: FolderDialog, tmp_path: Path) -> None:
    assert not dialog.validate()
    assert not dialog.apply.isEnabled()
    dialog.path.setText(str(tmp_path / "good"))
    dialog.path.editingFinished.emit()
    assert dialog.apply.isEnabled()
    assert dialog.chosen_path is not None
    assert dialog.move_data
    dialog.move_box.setChecked(False)
    assert dialog.apply.isEnabled()
    dialog.path.setText("  ")
    assert not dialog.validate()


def test_dialog_rejects_current_folder(dialog: FolderDialog, gui: GuiContext) -> None:
    dialog.path.setText(str(gui.current.root))
    assert not dialog.validate()
    assert dialog.chosen_path is None
    assert not dialog.apply.isEnabled()


def test_dialog_oserror_is_a_verdict(
    dialog: FolderDialog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> list[str]:
        raise OSError("denied")

    monkeypatch.setattr(data_folder_dialog, "validate_new_root", boom)
    dialog.path.setText(str(tmp_path / "w"))
    assert not dialog.validate()


def test_dialog_cloud_warning_and_retranslate(
    dialog: FolderDialog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gui: GuiContext
) -> None:
    monkeypatch.setattr(data_folder_dialog, "is_cloud_synced", always)
    dialog.path.setText(str(tmp_path / "cloudy"))
    assert dialog.validate()
    gui.language.set_language("ru")
    gui.language.set_language("en")
    assert dialog.apply.isEnabled()


def test_dialog_browse(
    dialog: FolderDialog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = str(tmp_path / "picked")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_a: chosen))
    dialog.browse.click()
    assert dialog.path.text() == chosen
    assert dialog.apply.isEnabled()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_a: ""))
    dialog.browse.click()
    assert dialog.path.text() == chosen
    dialog.path.clear()
    dialog.browse.click()
    dialog.cancel.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
