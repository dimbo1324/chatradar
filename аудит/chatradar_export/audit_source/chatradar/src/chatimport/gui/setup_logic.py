"""Qt-free logic of the first-run wizard: chat links, the data folder and the saved state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from chatimport.config import ConfigError, load_config
from chatimport.gui.key_validation import validate_api_hash, validate_api_id
from chatimport.library import LibraryError, add_entry, identity_of, load_library
from chatimport.paths import is_cloud_synced, normalize_root, resolve_root
from chatimport.ports import ChatImportError
from chatimport.refs import RefKind, display_ref, parse_ref
from chatimport.setroot import validate_new_root

if TYPE_CHECKING:
    from pathlib import Path

type RefStatus = Literal["added", "duplicate", "invalid", "error"]

_SEPARATORS: Final = re.compile(r"[\s,;]+")


@dataclass(frozen=True, slots=True)
class RefResult:
    ref: str
    status: RefStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FolderCheck:
    path: Path | None
    error: str = ""
    cloud: bool = False
    changed: bool = False


@dataclass(frozen=True, slots=True)
class SetupState:
    keys_saved: bool
    signed_in: bool
    chats: int
    root: Path


def split_refs(text: str) -> list[str]:
    return [part for part in _SEPARATORS.split(text.strip()) if part]


def add_refs(library_file: Path, text: str) -> list[RefResult]:
    """Add every link or username in `text` to the library; one result per reference.

    Only public usernames, links and numeric ids are accepted: a bare title cannot be told
    from a typo. Invite links are reported in their masked form.
    """
    refs = split_refs(text)
    try:
        known = {identity_of(entry.ref) for entry in load_library(library_file).entries}
    except LibraryError as error:
        return [RefResult(display_ref(ref), "error", str(error)) for ref in refs]
    results: list[RefResult] = []
    for ref in refs:
        shown = display_ref(ref)
        parsed = parse_ref(ref)
        if parsed.kind is RefKind.TITLE:
            results.append(RefResult(shown, "invalid"))
        elif parsed.identity in known:
            results.append(RefResult(shown, "duplicate"))
        else:
            try:
                add_entry(library_file, ref)
            except LibraryError as error:
                results.append(RefResult(shown, "error", str(error)))
            else:
                known.add(parsed.identity)
                results.append(RefResult(shown, "added"))
    return results


def current_root(config_file: Path) -> Path:
    try:
        configured = load_config(config_file).output.root_dir
    except ConfigError:
        configured = ""
    return resolve_root(None, configured)


def check_folder(text: str, current: Path, app_base: Path) -> FolderCheck:
    """Whether the typed folder can hold the archive; an empty text means the current one."""
    typed = text.strip()
    target = normalize_root(typed) if typed else current
    changed = target.expanduser().resolve() != current.expanduser().resolve()
    try:
        if changed:
            validate_new_root(target, current, app_base=app_base, move=False)
        else:
            _require_apart(target, app_base)
    except (ChatImportError, OSError) as error:
        return FolderCheck(None, str(error))
    return FolderCheck(target, cloud=is_cloud_synced(target), changed=changed)


def _require_apart(target: Path, app_base: Path) -> None:
    folder, base = target.expanduser().resolve(), app_base.expanduser().resolve()
    if folder.is_relative_to(base) or base.is_relative_to(folder):
        raise ChatImportError(
            "the data folder must be apart from the application folder, which holds "
            "the Telegram session"
        )


def read_state(config_file: Path, session_file: Path, library_file: Path) -> SetupState:
    try:
        telegram = load_config(config_file).telegram
        keys = (
            validate_api_id(str(telegram.api_id)) is None
            and validate_api_hash(telegram.api_hash) is None
        )
    except ConfigError:
        keys = False
    try:
        chats = len(load_library(library_file).entries)
    except LibraryError:
        chats = 0
    return SetupState(keys, session_file.is_file(), chats, current_root(config_file))
