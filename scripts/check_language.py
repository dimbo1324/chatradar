"""Repository language policy: everything tracked by git is English.

Fails on any Cyrillic character in a tracked or new (not ignored) text file, except under
``ALLOWED_PREFIXES``: data that is Russian or Spanish by nature (anonymized test fixtures).
Code that reads that data stays English.

Usage: uv run python scripts/check_language.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ALLOWED_PREFIXES: tuple[str, ...] = ("tests/fixtures/",)
BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".woff", ".woff2", ".db"}
)
CYRILLIC = re.compile("[\u0400-\u052f\u1c80-\u1c8f\u2de0-\u2dff\ua640-\ua69f]")


def candidate_files(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return sorted({f for f in output.split("\0") if f})


def is_checked(path: str) -> bool:
    return (
        not path.startswith(ALLOWED_PREFIXES) and Path(path).suffix.lower() not in BINARY_SUFFIXES
    )


def find_hits(root: Path, files: list[str]) -> list[str]:
    hits: list[str] = []
    for rel in filter(is_checked, files):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError, FileNotFoundError, IsADirectoryError, PermissionError:
            continue
        hits += [
            f"{rel}:{number}"
            for number, line in enumerate(text.split(chr(10)), start=1)
            if CYRILLIC.search(line)
        ]
    return hits


def main(root: Path = ROOT) -> int:
    files = candidate_files(root)
    hits = find_hits(root, files)
    if hits:
        listing = "\n  ".join(hits[:50])
        more = f"\n  ... and {len(hits) - 50} more" if len(hits) > 50 else ""
        sys.stderr.write(f"ERR non-English (Cyrillic) text in tracked files:\n  {listing}{more}\n")
        return 1
    sys.stdout.write(f"ok  language: {len(files)} files, English only\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
