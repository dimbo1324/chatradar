"""Small blocking dialogs and file openers for the tray; each runs on a worker thread."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

LOG_FILE_RE: Final = re.compile(r".+\.log(?:\.[0-9]+)?", re.IGNORECASE)
"""`chatimport.log` and its rotated copies `chatimport.log.1`, never anything that the
shell would run when opened."""


@contextmanager
def _tk_root() -> Generator[Any]:
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # pyright: ignore[reportUnknownMemberType]
    try:
        yield root
    finally:
        root.destroy()


def confirm(title: str, question: str) -> bool:
    from tkinter import messagebox

    with _tk_root() as root:
        return bool(messagebox.askyesno(title, question, parent=root))


def choose_folder() -> str:
    from tkinter import filedialog

    with _tk_root() as root:
        return str(filedialog.askdirectory(title="Choose the ChatImport folder", parent=root))


def ask_move() -> bool | None:
    from tkinter import messagebox

    with _tk_root() as root:
        answer = messagebox.askyesnocancel(
            "Change folder",
            "Move the downloaded data to the new folder?\n\n"
            "Yes: move it.\nNo: leave the old data where it is and start fresh.\n"
            "Cancel: keep the current folder.",
            parent=root,
        )
        return None if answer is None else bool(answer)


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a folder, a .toml or a .log file of the user's own
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)])  # noqa: S603 - fixed argv, no shell


def latest_file(folder: Path) -> Path | None:
    """The newest log file in `folder`; other files are ignored, because opening an unknown
    file through the shell may run it."""
    try:
        files = [p for p in folder.iterdir() if LOG_FILE_RE.fullmatch(p.name) and p.is_file()]
    except OSError:
        return None
    return max(files, key=_modified, default=None)


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("-inf")
