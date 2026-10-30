from __future__ import annotations

import subprocess
import types
from typing import TYPE_CHECKING, Any

import pytest

from scripts import doctor

if TYPE_CHECKING:
    from pathlib import Path

ALL_TOOLS = {"git", "uv", "just", "gh"}


class Machine:
    """Scripts which tools exist and what they print; patched in place of `shutil`/`subprocess`."""

    def __init__(self) -> None:
        self.installed = set(ALL_TOOLS)
        self.outputs: dict[tuple[str, ...], tuple[int, str, str]] = {}
        self.errors: dict[str, BaseException] = {}
        self.calls: list[tuple[str, ...]] = []
        self.kwargs: list[dict[str, Any]] = []

    def which(self, name: str) -> str | None:
        return f"/bin/{name}" if name in self.installed else None

    def run(self, command: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        self.kwargs.append(kwargs)
        if command[0] in self.errors:
            raise self.errors[command[0]]
        code, out, err = self.outputs.get(command, (0, f"{command[0]} 1.0\nsecond line", ""))
        return subprocess.CompletedProcess(command, code, out, err)


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Machine:
    fake = Machine()
    monkeypatch.setattr(doctor, "shutil", types.SimpleNamespace(which=fake.which))
    monkeypatch.setattr(
        doctor,
        "subprocess",
        types.SimpleNamespace(run=fake.run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    return fake


def report(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


# ----------------------------------------------------------------------------- run()


def test_run_reports_the_first_output_line_of_a_successful_tool(machine: Machine) -> None:
    assert doctor.run(("git", "--version")) == (True, "git 1.0")


def test_run_falls_back_to_stderr_when_stdout_is_empty(machine: Machine) -> None:
    machine.outputs[("uv", "--version")] = (0, "", "uv from stderr\nmore")

    assert doctor.run(("uv", "--version")) == (True, "uv from stderr")


def test_run_tolerates_a_tool_that_prints_nothing(machine: Machine) -> None:
    machine.outputs[("just", "--version")] = (0, "", "")

    assert doctor.run(("just", "--version")) == (True, "")


def test_run_marks_a_nonzero_exit_as_failed_but_keeps_the_message(machine: Machine) -> None:
    machine.outputs[("uv", "python", "find", "3.14")] = (2, "", "No interpreter found")

    assert doctor.run(("uv", "python", "find", "3.14")) == (False, "No interpreter found")


def test_run_does_not_launch_a_tool_that_is_not_on_path(machine: Machine) -> None:
    machine.installed.discard("just")

    assert doctor.run(("just", "--version")) == (False, "not found on PATH")
    assert machine.calls == []


def test_run_survives_a_timeout_and_an_os_error(machine: Machine) -> None:
    machine.errors["git"] = subprocess.TimeoutExpired(["git"], 30)
    machine.errors["uv"] = OSError("permission denied")

    ok_git, detail_git = doctor.run(("git", "--version"))
    ok_uv, detail_uv = doctor.run(("uv", "--version"))

    assert (ok_git, ok_uv) == (False, False)
    assert "timed out" in detail_git
    assert detail_uv == "permission denied"


def test_run_uses_a_timeout_the_repo_root_and_no_shell(machine: Machine) -> None:
    doctor.run(("git", "--version"))

    kwargs = machine.kwargs[0]
    assert kwargs["timeout"] == 30
    assert kwargs["cwd"] == doctor.ROOT
    assert kwargs["capture_output"] is True
    assert "shell" not in kwargs


# ------------------------------ repo_state()


def test_repo_state_is_ok_with_a_venv_and_the_hook(machine: Machine) -> None:
    assert doctor.repo_state() == [
        (True, True, ".venv", "present"),
        (True, True, "pre-commit hook", "installed"),
    ]


def test_repo_state_names_the_fix_for_each_missing_piece(machine: Machine) -> None:
    (doctor.ROOT / ".venv").rmdir()
    (doctor.ROOT / ".git" / "hooks" / "pre-commit").unlink()

    assert doctor.repo_state() == [
        (False, True, ".venv", "run: uv sync"),
        (False, True, "pre-commit hook", "run: uv run pre-commit install"),
    ]


def test_a_venv_that_is_a_file_does_not_count(machine: Machine) -> None:
    (doctor.ROOT / ".venv").rmdir()
    (doctor.ROOT / ".venv").write_text("", encoding="utf-8")

    assert doctor.repo_state()[0][0] is False


# ----------------------------------------------------------------------------- main()


def test_everything_present_is_ready_and_exit_0(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    code = doctor.main()

    lines = report(capsys)
    assert code == 0
    assert lines[-1] == "ready to develop"
    assert not any(line.startswith(("ERR", "warn")) for line in lines)
    assert sum(line.startswith("ok  ") for line in lines) == 7
    assert any(line.startswith("ok   git") and line.endswith("git 1.0") for line in lines)
    assert "-> " not in "\n".join(lines)


@pytest.mark.parametrize("tool", ["git", "uv", "just"])
def test_a_missing_required_tool_fails_with_its_install_hint(
    machine: Machine, capsys: pytest.CaptureFixture[str], tool: str
) -> None:
    machine.installed.discard(tool)

    code = doctor.main()

    lines = report(capsys)
    assert code == 1
    assert lines[-1] == "fix the ERR lines above"
    errs = [line for line in lines if line.startswith("ERR ")]
    assert errs
    assert all("not found on PATH -> " in line for line in errs)


def test_missing_uv_fails_both_the_uv_and_the_python_check(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    machine.installed.discard("uv")

    doctor.main()

    errs = [line for line in report(capsys) if line.startswith("ERR ")]
    assert len(errs) == 2
    assert any("python 3.14 (uv)" in line and "uv python install 3.14" in line for line in errs)


def test_a_missing_optional_tool_only_warns(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    machine.installed.discard("gh")

    code = doctor.main()

    lines = report(capsys)
    assert code == 0
    warns = [line for line in lines if line.startswith("warn")]
    assert len(warns) == 1
    assert "gh (GitHub CLI)" in warns[0]
    assert "winget install GitHub.cli" in warns[0]
    assert lines[-1] == "ready to develop"


def test_a_failing_optional_tool_does_not_hide_a_required_failure(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    machine.installed -= {"gh", "git"}

    code = doctor.main()

    lines = report(capsys)
    assert code == 1
    assert sum(line.startswith("ERR ") for line in lines) == 1
    assert sum(line.startswith("warn") for line in lines) == 1


@pytest.mark.parametrize("missing", [".venv", "hook"])
def test_missing_venv_or_hook_is_a_required_failure(
    machine: Machine, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    if missing == ".venv":
        (doctor.ROOT / ".venv").rmdir()
    else:
        (doctor.ROOT / ".git" / "hooks" / "pre-commit").unlink()

    code = doctor.main()

    assert code == 1
    assert any(line.startswith("ERR ") for line in report(capsys))


def test_a_timeout_in_one_tool_is_reported_as_an_error_not_a_crash(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    machine.errors["just"] = subprocess.TimeoutExpired(["just"], 30)

    code = doctor.main()

    lines = report(capsys)
    assert code == 1
    assert any(line.startswith("ERR ") and "just" in line and "timed out" in line for line in lines)
    assert any(line.startswith("ok  ") and "git" in line for line in lines)


def test_every_check_has_a_hint_and_a_real_command() -> None:
    assert [check.name for check in doctor.CHECKS if check.required] == [
        "git",
        "uv",
        "python 3.14 (uv)",
        "just",
    ]
    for check in doctor.CHECKS:
        assert check.hint
        assert check.command


def test_names_are_padded_so_details_line_up(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    doctor.main()

    tool_lines = [line for line in report(capsys) if line.endswith(" 1.0")]
    assert len(tool_lines) == 5
    assert {line[24:].split()[0] for line in tool_lines} == ALL_TOOLS | {"uv"}
