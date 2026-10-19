"""Read-only toolchain check: is this machine ready to develop ChatRadar?

Usage: python scripts/doctor.py   (stdlib only, runs before `uv sync`)
Exit code 1 when a required tool is missing; optional tools only warn.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    required: bool
    hint: str


CHECKS: tuple[Check, ...] = (
    Check("git", ("git", "--version"), True, "https://git-scm.com/downloads"),
    Check("uv", ("uv", "--version"), True, "winget install astral-sh.uv"),
    Check(
        "python 3.13 (uv)",
        ("uv", "python", "find", "3.13"),
        True,
        "uv python install 3.13",
    ),
    Check("just", ("just", "--version"), True, "winget install Casey.Just"),
    Check("docker cli", ("docker", "--version"), False, "install Docker Desktop"),
    Check(
        "docker daemon",
        ("docker", "info", "--format", "{{.ServerVersion}}"),
        False,
        "start Docker Desktop",
    ),
    Check("gh (GitHub CLI)", ("gh", "--version"), False, "winget install GitHub.cli"),
)


def run(command: tuple[str, ...]) -> tuple[bool, str]:
    if shutil.which(command[0]) is None:
        return False, "not found on PATH"
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv from CHECKS, no shell
            command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    output = (result.stdout or result.stderr).strip().splitlines()
    return result.returncode == 0, output[0] if output else ""


def repo_state() -> list[tuple[bool, bool, str, str]]:
    """(ok, required, name, detail) for things that live in the clone, not on PATH."""
    hook = ROOT / ".git" / "hooks" / "pre-commit"
    return [
        (
            (ROOT / ".venv").is_dir(),
            True,
            ".venv",
            "present" if (ROOT / ".venv").is_dir() else "run: uv sync",
        ),
        (
            hook.is_file(),
            True,
            "pre-commit hook",
            "installed" if hook.is_file() else "run: uv run pre-commit install",
        ),
        (
            (ROOT / ".env").is_file(),
            False,
            ".env",
            "present" if (ROOT / ".env").is_file() else "optional: cp .env.example .env",
        ),
    ]


def main() -> int:
    failed = False
    rows: list[tuple[bool, bool, str, str]] = []
    for check in CHECKS:
        ok, detail = run(check.command)
        rows.append((ok, check.required, check.name, detail if ok else f"{detail} -> {check.hint}"))
    rows += repo_state()
    for ok, required, name, detail in rows:
        mark = "ok  " if ok else ("ERR " if required else "warn")
        failed |= required and not ok
        sys.stdout.write(f"{mark} {name:<18} {detail}\n")
    sys.stdout.write("\nready to develop\n" if not failed else "\nfix the ERR lines above\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
