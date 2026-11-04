from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QLabel

from chatimport.gui.models.snapshot import ServiceError
from chatimport.gui.pages.library_dialog import LibraryDialog, _EntryRow
from chatimport.library import ChatEntry, load_library
from chatimport.resolution import resolve_error_key

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.gui.context import GuiContext

INVITE = "https://t.me/+AbCdEfGhIjKlMnOp"


@pytest.fixture
def library_file(gui: GuiContext) -> Path:
    path = gui.service.library_file
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_library(path: Path) -> None:
    path.write_text(
        '[[chat]]\nref = "@alpha_group"\nname = "alpha"\n\n'
        f'[[chat]]\nref = "{INVITE}"\nenabled = false\n',
        encoding="utf-8",
    )


def rows(dialog: LibraryDialog) -> list[_EntryRow]:
    return dialog.findChildren(_EntryRow)


def labels(dialog: LibraryDialog) -> list[str]:
    return [label.text() for label in dialog.findChildren(QLabel)]


def test_empty_library_shows_the_hint(gui: GuiContext, library_file: Path) -> None:
    dialog = LibraryDialog(gui)
    assert rows(dialog) == []
    assert any("chats.lib.empty" not in text and text for text in labels(dialog))
    assert dialog._problem.isHidden()


def test_entries_are_listed_with_masked_invites(gui: GuiContext, library_file: Path) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    shown = labels(dialog)
    assert len(rows(dialog)) == 2
    assert "alpha" in shown
    assert "@alpha_group" in shown
    assert all("AbCdEfGhIjKlMnOp" not in text for text in shown)


def test_unresolved_entry_gets_a_chip(gui: GuiContext, library_file: Path) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    baseline = len(dialog.findChildren(QLabel))
    failing = resolve_error_key(ChatEntry("@alpha_group"))
    dialog.set_errors(
        [ServiceError(failing, "nope"), ServiceError("worker:1", "other")],
    )
    assert len(dialog.findChildren(QLabel)) > baseline - 1
    assert len(rows(dialog)) == 2


def test_toggle_writes_the_file(gui: GuiContext, library_file: Path) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    first = next(row for row in rows(dialog) if row._entry.ref == "@alpha_group")
    first._switch.setChecked(False)
    entries = {entry.ref: entry for entry in load_library(library_file).entries}
    assert entries["@alpha_group"].enabled is False
    assert dialog._problem.isHidden()
    second = next(row for row in rows(dialog) if row._entry.ref == INVITE)
    second._switch.setChecked(True)
    assert load_library(library_file).find(INVITE) is not None
    assert next(e for e in load_library(library_file).entries if e.ref == INVITE).enabled is True


def test_toggle_of_a_vanished_entry_reports_the_problem(
    gui: GuiContext, library_file: Path
) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    library_file.write_text("", encoding="utf-8")
    row = rows(dialog)[0]
    row._switch.setChecked(not row._switch.isChecked())
    assert not dialog._problem.isHidden()
    assert rows(dialog) == []


def test_unreadable_library_shows_the_problem(gui: GuiContext, library_file: Path) -> None:
    library_file.write_text("[[chat]\nref = ", encoding="utf-8")
    dialog = LibraryDialog(gui)
    assert not dialog._problem.isHidden()
    assert rows(dialog) == []


def test_add_entry_appends_and_clears_the_form(gui: GuiContext, library_file: Path) -> None:
    dialog = LibraryDialog(gui)
    dialog._ref.setText("@new_group")
    dialog._name.setText("fresh")
    dialog._add.click()
    assert dialog._ref.text() == ""
    assert dialog._name.text() == ""
    assert not dialog._problem.isHidden()
    entry = load_library(library_file).entries[0]
    assert (entry.ref, entry.name, entry.enabled) == ("@new_group", "fresh", True)
    assert len(rows(dialog)) == 1


def test_add_without_a_name_and_via_return_key(gui: GuiContext, library_file: Path) -> None:
    dialog = LibraryDialog(gui)
    dialog._ref.setText("@plain_group")
    dialog._ref.returnPressed.emit()
    assert load_library(library_file).entries[0].name is None


@pytest.mark.parametrize(("ref", "name"), [("", ""), ("@x_group", "   ")])
def test_add_rejects_bad_input(gui: GuiContext, library_file: Path, ref: str, name: str) -> None:
    dialog = LibraryDialog(gui)
    dialog._ref.setText(ref)
    dialog._name.setText(name)
    dialog._add.click()
    assert not dialog._problem.isHidden()
    assert not library_file.exists() or load_library(library_file).entries == ()
    assert dialog._ref.text() == ref


def test_add_duplicate_is_rejected(gui: GuiContext, library_file: Path) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    dialog._ref.setText("@alpha_group")
    dialog._add.click()
    assert not dialog._problem.isHidden()
    assert len(load_library(library_file).entries) == 2


def test_successful_toggle_hides_an_earlier_problem(gui: GuiContext, library_file: Path) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    dialog._ref.setText("")
    dialog._add.click()
    assert not dialog._problem.isHidden()
    rows(dialog)[0]._switch.setChecked(False)
    assert dialog._problem.isHidden()


def test_close_button_accepts(gui: GuiContext, library_file: Path) -> None:
    dialog = LibraryDialog(gui)
    dialog.show()
    dialog._close.click()
    assert not dialog.isVisible()


def test_language_switch_retranslates(gui: GuiContext, library_file: Path) -> None:
    write_library(library_file)
    dialog = LibraryDialog(gui)
    english = dialog.windowTitle()
    gui.language.set_language("ru")
    assert dialog.windowTitle() != english
    assert len(rows(dialog)) == 2
