from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from chatradar import cli_learning
from chatradar.domain.evaluation import MessageLabel
from chatradar.domain.models import Source
from tests.unit.learning.fakes import CHAT, NOW, FakeLabels, FakeLexicon, FakeScanner, make_message
from tests.unit.learning.test_generators import background, spam_messages
from tests.unit.test_eval import FakeMessages, FakeQueries, stored, write_truth

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    import pytest

    from chatradar.domain.models import StoredMessage

runner = CliRunner()


class FakeRepo(FakeMessages, FakeQueries, FakeScanner):
    def __init__(self, messages: list[StoredMessage]) -> None:
        FakeMessages.__init__(self, messages)
        FakeQueries.__init__(self, [CHAT])
        FakeScanner.__init__(self, messages)


def install(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[StoredMessage],
    labels: FakeLabels | None = None,
) -> FakeLexicon:
    lexicon = FakeLexicon()
    runtime = SimpleNamespace(
        repo=FakeRepo(messages), lexicon=lexicon, labels=labels or FakeLabels()
    )

    @asynccontextmanager
    async def fake_open_runtime(settings: Any) -> AsyncGenerator[SimpleNamespace]:
        yield runtime

    monkeypatch.setattr(cli_learning, "open_runtime", fake_open_runtime)
    return lexicon


def test_eval_requires_a_source() -> None:
    result = runner.invoke(cli_learning.learning_app, ["eval"])

    assert result.exit_code == 2
    assert "--truth" in result.output


def test_eval_prints_a_table_for_truth_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write_truth(
        tmp_path / "t.json",
        CHAT,
        [{"msg_id": "1", "is_noise": True, "reason": "spam", "is_question": False, "lang": None}],
    )
    install(monkeypatch, [stored(1, is_noise=True, noise_reason="spam", is_question=False)])

    result = runner.invoke(cli_learning.learning_app, ["eval", "--truth", str(path)])

    assert result.exit_code == 0, result.output
    assert "source: truth-file; compared 1, missing 0" in result.output
    assert "spam" in result.output
    assert "noise=3" in result.output


def test_eval_json_is_parseable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = write_truth(tmp_path / "t.json", CHAT, [{"msg_id": "1", "is_noise": False}])
    install(monkeypatch, [stored(1, is_noise=False)])

    result = runner.invoke(cli_learning.learning_app, ["eval", "--truth", str(path), "--json"])

    report = json.loads(result.output)
    assert report["source"] == "truth-file"
    assert report["total"] == 1
    assert report["noise"]["label"] == "noise"


def test_eval_labels_uses_the_human_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    label = MessageLabel(
        source=Source.TELEGRAM,
        chat_id=CHAT,
        msg_id="1",
        is_noise=True,
        reason="spam",
        created_at=NOW,
    )
    install(
        monkeypatch,
        [stored(1, is_noise=True, noise_reason="spam")],
        FakeLabels([label]),
    )

    result = runner.invoke(cli_learning.learning_app, ["eval", "--labels"])

    assert result.exit_code == 0, result.output
    assert "source: human-labels; compared 1, missing 0" in result.output


def test_mine_prints_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [*background(300), *spam_messages("Earn five hundred weekly, write me in DM", 8)]
    messages += [make_message(1, "unused")]
    lexicon = install(monkeypatch, messages)
    monkeypatch.setenv("CHATRADAR_LEARNING__MIN_SCORE", "1.0")
    cli_learning.get_settings.cache_clear()

    result = runner.invoke(cli_learning.learning_app, ["mine"])

    assert result.exit_code == 0, result.output
    assert "scanned 309 messages" in result.output
    assert "spam_offers=" in result.output
    assert lexicon.terms
    assert len(lexicon.dormant_calls) == 1
