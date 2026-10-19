from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from scripts import check_language, sync_agents

if TYPE_CHECKING:
    from pathlib import Path

AGENT = """---
name: demo-agent
description: Demo agent.
tools: Read
---

Body of the agent.
"""

SKILL = """---
name: demo-skill
description: Demo skill.
---

# Demo
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def rules_repo(tmp_path: Path) -> Path:
    _write(tmp_path / ".ai/universal/01-alpha.md", "# Alpha\n\nAlways inline.\n")
    _write(
        tmp_path / ".ai/project/10-beta.md",
        "# Beta\n\n<!-- tier: extended -->\n\n> **Essence.** Beta in one line.\n\nLong text.\n",
    )
    _write(tmp_path / ".claude/agents/demo-agent.md", AGENT)
    _write(tmp_path / ".claude/skills/demo-skill/SKILL.md", SKILL)
    return tmp_path


def test_sync_writes_agents_md_and_codex_mirror(rules_repo: Path) -> None:
    assert sync_agents.main([], root=rules_repo) == 0

    agents_md = (rules_repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "GENERATED FILE - DO NOT EDIT." in agents_md
    assert "Always inline." in agents_md
    assert "Long text." not in agents_md
    assert "Beta in one line." in agents_md

    toml = (rules_repo / ".codex/agents/demo-agent.toml").read_text(encoding="utf-8")
    assert 'name = "demo-agent"' in toml
    assert "Body of the agent." in toml
    skill = (rules_repo / ".codex/skills/demo-skill/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\n# GENERATED from .claude/skills/demo-skill/SKILL.md")


def test_check_detects_drift_and_stale_files(rules_repo: Path) -> None:
    sync_agents.main([], root=rules_repo)
    assert sync_agents.main(["--check"], root=rules_repo) == 0

    _write(rules_repo / ".ai/universal/01-alpha.md", "# Alpha\n\nChanged.\n")
    assert sync_agents.main(["--check"], root=rules_repo) == 1

    sync_agents.main([], root=rules_repo)
    _write(rules_repo / ".codex/agents/orphan.toml", "name = 'orphan'\n")
    assert sync_agents.main(["--check"], root=rules_repo) == 1
    sync_agents.main([], root=rules_repo)
    assert not (rules_repo / ".codex/agents/orphan.toml").exists()


def test_agent_without_frontmatter_is_rejected(rules_repo: Path) -> None:
    _write(rules_repo / ".claude/agents/broken.md", "no frontmatter\n")

    assert sync_agents.main([], root=rules_repo) == 1


def test_budget_is_enforced(rules_repo: Path) -> None:
    _write(rules_repo / ".ai/universal/02-huge.md", "# Huge\n\n" + "x" * 40_000 + "\n")

    assert sync_agents.main([], root=rules_repo) == 1


def test_repository_agents_are_in_sync() -> None:
    assert sync_agents.main(["--check"]) == 0


@pytest.mark.parametrize(
    ("path", "checked"),
    [
        ("src/chatradar/cli.py", True),
        ("README.md", True),
        ("tests/fixtures/chat.json", False),
        ("src/chatradar/resources/lexicons/gratitude.txt", False),
        ("docs/logo.png", False),
    ],
)
def test_language_allowlist(path: str, checked: bool) -> None:
    assert check_language.is_checked(path) is checked


def test_language_hits_report_file_and_line(tmp_path: Path) -> None:
    _write(tmp_path / "ok.md", "English only\n")
    _write(tmp_path / "bad.md", "line one\n\u043f\u0440\u0438\u0432\u0435\u0442\n")
    _write(tmp_path / "tests/fixtures/data.txt", "\u043f\u0440\u0438\u0432\u0435\u0442\n")

    hits = check_language.find_hits(tmp_path, ["ok.md", "bad.md", "tests/fixtures/data.txt"])

    assert hits == ["bad.md:2"]


def test_language_main_on_a_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # noqa: S607
    _write(tmp_path / "a.md", "fine\n")
    assert check_language.main(root=tmp_path) == 0

    _write(tmp_path / "b.md", "\u0434\u0430\n")
    assert check_language.main(root=tmp_path) == 1
