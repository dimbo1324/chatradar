from __future__ import annotations

import pytest
from typer.testing import CliRunner

from chatradar.cli_lexicon import lexicon_app

runner = CliRunner()

pytestmark = pytest.mark.integration


def test_list_shows_seed_terms_with_total() -> None:
    result = runner.invoke(lexicon_app, ["list", "--kind", "gratitude", "--lang", "en"])

    assert result.exit_code == 0, result.output
    assert "thanks" in result.stdout
    assert " of " in result.stdout.splitlines()[-1]


def test_list_limit_and_status_filter() -> None:
    result = runner.invoke(lexicon_app, ["list", "--status", "candidate", "--limit", "3"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip().splitlines()[-1] == "0 of 0"


def test_stats_reports_revision_and_counts() -> None:
    result = runner.invoke(lexicon_app, ["stats"])

    assert result.exit_code == 0, result.output
    assert "revision: 1" in result.stdout
    assert "applied noise: 0" in result.stdout
    assert "pending apply: yes" in result.stdout
    assert "candidate: 0" in result.stdout


def test_reject_accept_reset_move_the_revision() -> None:
    rejected = runner.invoke(
        lexicon_app, ["reject", "gratitude", "thanks", "--lang", "en", "--note", "too broad"]
    )
    assert rejected.exit_code == 0, rejected.output
    assert "rejected: gratitude/en/thanks" in rejected.stdout
    assert "revision: 2" in rejected.stdout

    accepted = runner.invoke(lexicon_app, ["accept", "gratitude", "thanks", "--lang", "en"])
    assert "active: gratitude/en/thanks" in accepted.stdout
    assert "revision: 3" in accepted.stdout

    reset = runner.invoke(lexicon_app, ["reset", "gratitude", "thanks", "--lang", "en"])
    assert "candidate: gratitude/en/thanks" in reset.stdout
    assert "revision: 4" in reset.stdout


def test_decision_on_unknown_term_fails() -> None:
    result = runner.invoke(lexicon_app, ["accept", "gratitude", "no such phrase"])

    assert result.exit_code == 1
    assert "unknown term" in result.stderr


def test_add_creates_an_active_human_term_once() -> None:
    added = runner.invoke(lexicon_app, ["add", "questions", "Whereabouts", "--lang", "en"])
    assert added.exit_code == 0, added.output
    assert "active: questions/en/whereabouts" in added.stdout
    assert "revision: 2" in added.stdout

    again = runner.invoke(lexicon_app, ["add", "questions", "whereabouts", "--lang", "en"])
    assert "revision: 2" in again.stdout

    listed = runner.invoke(lexicon_app, ["list", "--kind", "questions", "--lang", "en"])
    assert "human" in listed.stdout
    assert "whereabouts" in listed.stdout


def test_add_keeps_symbols() -> None:
    result = runner.invoke(lexicon_app, ["add", "gratitude", "+++"])

    assert result.exit_code == 0, result.output
    assert "active: gratitude/any/+++" in result.stdout


def test_unknown_kind_is_a_usage_error() -> None:
    result = runner.invoke(lexicon_app, ["add", "weather", "rain"])

    assert result.exit_code == 2
