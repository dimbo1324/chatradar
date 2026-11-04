# pyright: reportPrivateUsage=false
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from chatimport import autostart
from chatimport.autostart import (
    MODULE_ARGUMENTS,
    TASK_NAME,
    AutostartError,
    AutostartState,
    AutostartStatus,
    build_task_xml,
)
from chatimport.ports import ChatImportError


def done(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(["schtasks"], returncode, stdout, stderr)


class FakeSchtasks:
    """Replaces `subprocess.run` inside the module: replies per schtasks verb, records calls."""

    def __init__(self) -> None:
        self.replies: dict[str, subprocess.CompletedProcess[bytes] | BaseException] = {}
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.definitions: list[bytes] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(argv)
        self.kwargs.append(kwargs)
        if argv[1] == "/Create":
            self.definitions.append(Path(argv[argv.index("/XML") + 1]).read_bytes())
        reply = self.replies.get(argv[1], done())
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def verbs(self) -> list[str]:
        return [call[1] for call in self.calls]


@pytest.fixture
def schtasks(monkeypatch: pytest.MonkeyPatch) -> FakeSchtasks:
    fake = FakeSchtasks()
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    return fake


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart, "supported", lambda: True)


@pytest.fixture
def elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart, "supported", lambda: False)


@pytest.fixture
def python(tmp_path: Path) -> str:
    path = tmp_path / "py dir" / "python.exe"
    path.parent.mkdir()
    path.write_bytes(b"")
    return str(path)


def registered_xml(
    program: str, arguments: str = MODULE_ARGUMENTS, *, enabled: bool = True
) -> bytes:
    xml = build_task_xml(program, arguments, "HOST\\someone")
    if not enabled:
        head, tail = xml.split("<Settings>")
        tail = tail.replace("<Enabled>true</Enabled>", "<Enabled> false </Enabled>", 1)
        xml = head + "<Settings>" + tail
    return xml.encode("utf-16")


@pytest.mark.parametrize(("platform", "expected"), [("win32", True), ("linux", False)])
def test_supported_follows_the_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, expected: bool
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    assert autostart.supported() is expected


def test_status_properties() -> None:
    assert AutostartStatus(AutostartState.ENABLED).enabled
    assert not AutostartStatus(AutostartState.DISABLED).enabled
    assert AutostartStatus(AutostartState.ABSENT).supported
    assert not AutostartStatus(AutostartState.UNSUPPORTED).supported


def test_error_carries_reason_and_is_a_chat_import_error() -> None:
    error = AutostartError("denied", "no")
    assert error.reason == "denied"
    assert isinstance(error, ChatImportError)


def test_launcher_prefers_the_windowless_interpreter(python: str) -> None:
    windowless = Path(python).with_name("pythonw.exe")
    assert autostart.launcher(python) == python
    windowless.write_bytes(b"")
    assert autostart.launcher(python) == str(windowless)
    assert autostart.task_command(python) == (str(windowless), MODULE_ARGUMENTS)


def test_launcher_defaults_to_the_running_interpreter() -> None:
    assert Path(autostart.launcher()).name in {Path(sys.executable).name, "pythonw.exe"}


def test_task_xml_escapes_user_program_and_arguments() -> None:
    xml = build_task_xml("C:\\A & B\\py<>.exe", "-m x & y", "DOM\\a&b")
    assert "DOM\\a&amp;b" in xml
    assert "&quot;" not in xml
    assert '"C:\\A &amp; B\\py&lt;&gt;.exe"' in xml
    assert "<Arguments>-m x &amp; y</Arguments>" in xml
    assert "<Delay>PT1M</Delay>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml


def test_current_user_with_and_without_a_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart.getpass, "getuser", lambda: "someone")
    monkeypatch.setenv("USERDOMAIN", "HOST")
    assert autostart._current_user() == "HOST\\someone"
    monkeypatch.delenv("USERDOMAIN")
    assert autostart._current_user() == "someone"


def test_schtasks_runs_without_a_shell_or_a_console_window(schtasks: FakeSchtasks) -> None:
    result = autostart._schtasks("/Query", "/TN", "X")
    assert result.returncode == 0
    assert schtasks.calls == [["schtasks", "/Query", "/TN", "X"]]
    options = schtasks.kwargs[0]
    assert options["capture_output"] is True
    assert options["check"] is False
    assert options["timeout"] == autostart._TIMEOUT_SECONDS
    assert options["creationflags"] == autostart._CREATE_NO_WINDOW


@pytest.mark.parametrize(
    "error", [FileNotFoundError("missing"), subprocess.TimeoutExpired("schtasks", 30)]
)
def test_schtasks_that_cannot_run_is_a_failed_error(
    schtasks: FakeSchtasks, error: BaseException
) -> None:
    schtasks.replies["/Query"] = error
    with pytest.raises(AutostartError, match=type(error).__name__) as caught:
        autostart._schtasks("/Query")
    assert caught.value.reason == "failed"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\xef\xbb\xbfplain", "plain"),
        ("wide \u00e9".encode("utf-16"), "wide \u00e9"),
        (b"\xff\xfe\x80", "\xff\xfe\u20ac"),
    ],
)
def test_text_decodes_the_encodings_schtasks_uses(raw: bytes, expected: str) -> None:
    assert autostart._text(raw) == expected


def test_failure_reads_stderr_then_stdout_and_classifies_denial() -> None:
    denied = autostart._failure(done(5, stderr=b"ERROR: Access is denied."))
    assert denied.reason == "denied"
    assert "exit code 5" in str(denied)
    other = autostart._failure(done(2, stdout=b"strange"))
    assert other.reason == "failed"
    assert "strange" in str(other)
    long = autostart._failure(done(2, stderr=b"x" * 500))
    assert len(str(long)) < 260


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (done(2, stderr=b"HRESULT 0x80070002"), True),
        (done(5, stderr=b"The system cannot find the file specified."), True),
        (done(5, stderr=b"Task does not exist"), True),
        (done(1, stderr=b"ERROR: something"), True),
        (done(1, stderr=b"ERROR: Access is denied"), False),
        (done(5, stderr=b"ERROR: other"), False),
    ],
)
def test_is_absent(result: subprocess.CompletedProcess[bytes], expected: bool) -> None:
    assert autostart._is_absent(result) is expected


def test_status_is_unsupported_off_windows(elsewhere: None, schtasks: FakeSchtasks) -> None:
    assert autostart.status() == AutostartStatus(AutostartState.UNSUPPORTED)
    assert schtasks.calls == []


def test_status_absent(windows: None, schtasks: FakeSchtasks) -> None:
    schtasks.replies["/Query"] = done(1, stderr=b"ERROR: cannot find the file")
    assert autostart.status().state is AutostartState.ABSENT
    assert schtasks.calls == [["schtasks", "/Query", "/TN", TASK_NAME, "/XML"]]


def test_status_failure_is_raised(windows: None, schtasks: FakeSchtasks) -> None:
    schtasks.replies["/Query"] = done(5, stderr=b"Access is denied")
    with pytest.raises(AutostartError) as caught:
        autostart.status()
    assert caught.value.reason == "denied"


def test_status_enabled_and_current(windows: None, schtasks: FakeSchtasks, python: str) -> None:
    schtasks.replies["/Query"] = done(stdout=registered_xml(python))
    result = autostart.status(executable=python)
    assert result.state is AutostartState.ENABLED
    assert result.enabled
    assert result.current is True
    assert result.command == f"{python} {MODULE_ARGUMENTS}"


def test_status_decodes_ampersands_in_the_registered_path(
    windows: None, schtasks: FakeSchtasks, tmp_path: Path
) -> None:
    folder = tmp_path / "a&b"
    folder.mkdir()
    exe = folder / "python.exe"
    exe.write_bytes(b"")
    schtasks.replies["/Query"] = done(stdout=registered_xml(str(exe)))
    assert autostart.status(executable=str(exe)).current is True


def test_status_flags_a_task_that_points_elsewhere(
    windows: None, schtasks: FakeSchtasks, python: str, tmp_path: Path
) -> None:
    schtasks.replies["/Query"] = done(stdout=registered_xml(str(tmp_path / "other.exe")))
    assert autostart.status(executable=python).current is False
    schtasks.replies["/Query"] = done(stdout=registered_xml(python, "-m old tray"))
    assert autostart.status(executable=python).current is False


def test_status_disabled(windows: None, schtasks: FakeSchtasks, python: str) -> None:
    schtasks.replies["/Query"] = done(stdout=registered_xml(python, enabled=False))
    result = autostart.status(executable=python)
    assert result.state is AutostartState.DISABLED
    assert not result.enabled
    assert result.supported


def test_status_tolerates_xml_without_the_expected_parts(
    windows: None, schtasks: FakeSchtasks, python: str
) -> None:
    schtasks.replies["/Query"] = done(stdout=b"<Task></Task>")
    result = autostart.status(executable=python)
    assert result.state is AutostartState.ENABLED
    assert result.current is False
    assert result.command == ""


def test_enable_is_refused_off_windows(elsewhere: None) -> None:
    with pytest.raises(AutostartError) as caught:
        autostart.enable()
    assert caught.value.reason == "unsupported"


def test_enable_registers_a_utf16_definition_and_reports_the_state(
    windows: None, schtasks: FakeSchtasks, python: str
) -> None:
    schtasks.replies["/Query"] = done(stdout=registered_xml(python))
    result = autostart.enable("Other", executable=python)

    assert result.state is AutostartState.ENABLED
    assert result.current is True
    assert schtasks.verbs() == ["/Create", "/Query"]
    create = schtasks.calls[0]
    assert create[2:4] == ["/TN", "Other"]
    assert create[-1] == "/F"
    (definition,) = schtasks.definitions
    assert definition.startswith(b"\xff\xfe")
    assert python in definition.decode("utf-16")
    assert not Path(create[create.index("/XML") + 1]).exists()


def test_enable_failure_is_raised_and_cleans_up(
    windows: None, schtasks: FakeSchtasks, python: str
) -> None:
    schtasks.replies["/Create"] = done(5, stderr=b"ERROR: Access is denied.")
    with pytest.raises(AutostartError) as caught:
        autostart.enable(executable=python)
    assert caught.value.reason == "denied"
    assert schtasks.verbs() == ["/Create"]


def test_disable_is_refused_off_windows(elsewhere: None) -> None:
    with pytest.raises(AutostartError) as caught:
        autostart.disable()
    assert caught.value.reason == "unsupported"


def test_disable_of_an_absent_task_deletes_nothing(windows: None, schtasks: FakeSchtasks) -> None:
    schtasks.replies["/Query"] = done(1, stderr=b"ERROR: cannot find")
    assert autostart.disable() == AutostartStatus(AutostartState.ABSENT)
    assert schtasks.verbs() == ["/Query"]


def test_disable_deletes_an_existing_task(
    windows: None, schtasks: FakeSchtasks, python: str
) -> None:
    schtasks.replies["/Query"] = done(stdout=registered_xml(python))
    assert autostart.disable("Other").state is AutostartState.ABSENT
    assert schtasks.verbs() == ["/Query", "/Delete"]
    assert schtasks.calls[1][2:] == ["/TN", "Other", "/F"]


def test_disable_failure_is_raised(windows: None, schtasks: FakeSchtasks, python: str) -> None:
    schtasks.replies["/Query"] = done(stdout=registered_xml(python))
    schtasks.replies["/Delete"] = done(5, stderr=b"Access is denied")
    with pytest.raises(AutostartError) as caught:
        autostart.disable()
    assert caught.value.reason == "denied"
