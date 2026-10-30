from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest

from scripts import sync_agents
from scripts.sync_agents import Module, SyncError

if TYPE_CHECKING:
    from pathlib import Path

AGENT = "---\nname: demo-agent\ndescription: Demo agent.\n---\n\nBody of the agent.\n"
SKILL = "---\nname: demo-skill\ndescription: Demo skill.\n---\n\n# Demo\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write(tmp_path / ".ai/universal/01-alpha.md", "# Alpha\n\nAlways inline.\n")
    write(tmp_path / ".ai/project/10-beta.md", "# Beta\n\nProject rule.\n")
    write(tmp_path / ".claude/agents/demo-agent.md", AGENT)
    write(tmp_path / ".claude/skills/demo-skill/SKILL.md", SKILL)
    return tmp_path


def run(root: Path, *args: str) -> int:
    return sync_agents.main(list(args), root=root)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# ----------------------------------------------------------------------------- Module


@pytest.mark.parametrize(
    ("body", "extended"),
    [
        ("# T\n<!-- tier: extended -->\ntext", True),
        ("# T\n\n\n\n<!-- tier: extended -->", True),
        ("# T\n\n\n\n\n<!-- tier: extended -->", False),
        ("# T\n\ntext\n\n\n\n\n\nlater <!-- tier: extended -->", False),
        ("# T\n\ntext", False),
        ("", False),
    ],
)
def test_tier_marker_counts_only_in_the_first_five_lines(body: str, extended: bool) -> None:
    assert Module(".ai/x.md", body).is_extended is extended


@pytest.mark.parametrize(
    ("body", "title"),
    [
        ("# Alpha  \n\ntext", "Alpha"),
        ("intro\n# Second line title", "Second line title"),
        ("## Not a title\ntext", "(untitled module)"),
        ("#hashtag\ntext", "(untitled module)"),
        ("", "(untitled module)"),
        ("# First\n# Second", "First"),
    ],
)
def test_module_title(body: str, title: str) -> None:
    assert Module(".ai/x.md", body).title == title


@pytest.mark.parametrize(
    ("body", "essence"),
    [
        ("# T\n\n> **Essence.** Short and sweet.\n", "Short and sweet."),
        ("# T\n\n   > **Essence.**   padded   \n", "padded"),
        ("# T\n\n> **Essence.** first\n> **Essence.** second\n", "first"),
        ("# T\n\nno essence here\n", None),
        ("# T\n\n> **Essence.**\n", ""),
        ("# T\n\nText with > **Essence.** in the middle\n", None),
    ],
)
def test_module_essence(body: str, essence: str | None) -> None:
    assert Module(".ai/x.md", body).essence == essence


# ------------------------------ render_agents_md


def test_agents_md_without_extended_modules_has_no_index() -> None:
    text = sync_agents.render_agents_md([Module(".ai/universal/a.md", "# A\n\nbody")])

    assert "module index" not in text
    assert "<!-- module: .ai/universal/a.md -->\n\n# A\n\nbody" in text
    assert text.startswith("<!--\nGENERATED FILE - DO NOT EDIT.")
    assert text.endswith("body\n")
    assert not text.endswith("\n\n")


def test_extended_modules_are_listed_by_title_file_and_essence_not_inlined() -> None:
    modules = [
        Module(".ai/universal/a.md", "# A\n\ninline body"),
        Module(
            ".ai/project/b.md",
            "# B\n<!-- tier: extended -->\n> **Essence.** B in brief.\nB long text",
        ),
        Module(".ai/project/c.md", "# C\n<!-- tier: extended -->\nC long text"),
    ]

    text = sync_agents.render_agents_md(modules)

    assert "inline body" in text
    assert "B long text" not in text
    assert "C long text" not in text
    index = text[text.index("<!-- module index: extended -->") :]
    assert "## B\n\nFile: `.ai/project/b.md`\n\nB in brief." in index
    assert "## C\n\nFile: `.ai/project/c.md`" in index
    assert index.index("## B") < index.index("## C")
    assert "<!-- module: .ai/project/b.md -->" not in text


def test_sections_are_separated_by_a_horizontal_rule() -> None:
    text = sync_agents.render_agents_md(
        [Module(".ai/universal/a.md", "# A"), Module(".ai/universal/b.md", "# B")]
    )

    assert text.count("\n\n---\n\n") == 2


# ------------------------------ frontmatter


def test_frontmatter_value_may_contain_colons_and_extra_spaces() -> None:
    meta, body = sync_agents.parse_frontmatter(
        "---\nname:   x \ndescription: Use when: a; b: c\nno colon line\n---\n\nBody\n---\nmore\n",
        "f.md",
    )

    assert meta["name"] == "x"
    assert meta["description"] == "Use when: a; b: c"
    assert body == "Body\n---\nmore"


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter",
        "---\nname: x\ndescription: y\n",
        "\n---\nname: x\ndescription: y\n---\nbody",
        "---\n---\nbody",
        "",
    ],
)
def test_frontmatter_must_open_and_close(text: str) -> None:
    with pytest.raises(SyncError, match=r"missing --- frontmatter ---"):
        sync_agents.parse_frontmatter(text, "f.md")


@pytest.mark.parametrize(
    ("block", "missing"),
    [
        ("description: y", "name"),
        ("name: x", "description"),
        ("name:\ndescription: y", "name"),
        ("name: x\ndescription:   ", "description"),
    ],
)
def test_frontmatter_requires_name_and_description(block: str, missing: str) -> None:
    with pytest.raises(SyncError, match=f"needs `{missing}`"):
        sync_agents.parse_frontmatter(f"---\n{block}\n---\nbody", "f.md")


# ------------------------------ codex agent


def test_codex_agent_is_valid_toml_that_round_trips_awkward_content() -> None:
    body = "Use C:\\path\\to and 'single' and \"double\" and '' and emoji \U0001f600 \u00e9\n\nend'"
    text = f'---\nname: odd\ndescription: Say "hi" \\ and \u00e9\neffort: medium\n---\n\n{body}\n'

    target, content = sync_agents.render_codex_agent("odd.md", text)

    parsed = tomllib.loads(content)
    assert target == ".codex/agents/odd.toml"
    assert parsed["description"] == 'Say "hi" \\ and \u00e9'
    assert parsed["developer_instructions"] == body + "\n"
    assert parsed["model_reasoning_effort"] == "medium"
    assert content.startswith("# GENERATED from .claude/agents/odd.md by just agents")


def test_codex_agent_defaults_to_high_effort_and_keeps_unicode_unescaped() -> None:
    _, content = sync_agents.render_codex_agent(
        "a.md", "---\nname: a\ndescription: caf\u00e9\n---\nBody"
    )

    assert tomllib.loads(content)["model_reasoning_effort"] == "high"
    assert "caf\u00e9" in content


def test_codex_agent_body_with_triple_quotes_is_rejected() -> None:
    with pytest.raises(SyncError, match="must not contain"):
        sync_agents.render_codex_agent("a.md", "---\nname: a\ndescription: d\n---\nx '''y")


def test_codex_skill_marker_is_inserted_after_the_first_fence_only() -> None:
    text = "---\nname: s\ndescription: d\n---\n\nbody\n---\nrule\n"

    target, content = sync_agents.render_codex_skill("s", text)

    assert target == ".codex/skills/s/SKILL.md"
    assert content.count("# GENERATED from") == 1
    assert content.startswith("---\n# GENERATED from .claude/skills/s/SKILL.md by just agents")
    assert content.endswith("body\n---\nrule\n")


def test_codex_skill_without_frontmatter_is_rejected() -> None:
    with pytest.raises(SyncError, match=r"s/SKILL.md: missing"):
        sync_agents.render_codex_skill("s", "# just text")


# ------------------------------ main: errors


def test_a_skill_without_frontmatter_fails_with_a_message(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / ".claude/skills/bad/SKILL.md", "# no frontmatter\n")

    assert run(repo) == 1
    assert "bad/SKILL.md: missing --- frontmatter ---" in capsys.readouterr().err
    assert not (repo / "AGENTS.md").exists()


def test_an_agent_with_a_missing_description_fails_and_writes_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / ".claude/agents/bad.md", "---\nname: bad\n---\nbody\n")

    assert run(repo) == 1
    assert "needs `description`" in capsys.readouterr().err
    assert not (repo / ".codex").exists()


def test_a_missing_module_directory_is_reported(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".ai/project/10-beta.md").unlink()
    (repo / ".ai/project").rmdir()

    assert run(repo) == 1
    assert "missing module directory" in capsys.readouterr().err


def test_empty_module_directories_are_reported(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".ai/universal/01-alpha.md").unlink()
    (repo / ".ai/project/10-beta.md").unlink()

    assert run(repo) == 1
    assert "no rule modules found" in capsys.readouterr().err


def test_non_markdown_files_among_modules_are_ignored(repo: Path) -> None:
    write(repo / ".ai/universal/notes.txt", "# Not a module\n")

    run(repo)

    assert "Not a module" not in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_two_agents_with_the_same_name_are_an_error_not_a_silent_overwrite(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / ".claude/agents/other-file.md", AGENT.replace("Body of the agent.", "Other body."))

    code = run(repo)

    assert code == 1
    assert "demo-agent" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["../../escape", "sub/dir", "..\\up", "a/../../b"])
def test_an_agent_name_cannot_point_outside_the_codex_agents_folder(repo: Path, name: str) -> None:
    write(repo / ".claude/agents/evil.md", f"---\nname: {name}\ndescription: d\n---\nbody\n")
    before = set(snapshot(repo))

    code = run(repo)

    stray = {
        rel
        for rel in set(snapshot(repo)) - before
        if not rel.startswith(".codex/agents/")
        and rel not in {"AGENTS.md"}
        and not rel.startswith(".codex/skills/")
    }
    assert code == 1
    assert stray == set()


def test_a_skill_folder_without_skill_md_is_a_clean_error(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".claude/skills/empty").mkdir()

    assert run(repo) == 1
    assert "empty" in capsys.readouterr().err


def test_a_repo_without_a_skills_folder_still_syncs(repo: Path) -> None:
    (repo / ".claude/skills/demo-skill/SKILL.md").unlink()
    (repo / ".claude/skills/demo-skill").rmdir()
    (repo / ".claude/skills").rmdir()

    assert run(repo) == 0
    assert (repo / "AGENTS.md").is_file()


def test_unknown_arguments_exit_with_the_argparse_code(repo: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(repo, "--bogus")

    assert exit_info.value.code == 2


# ------------------------------ main: budget


def padded_repo(repo: Path, extra_bytes: int) -> None:
    write(repo / ".ai/universal/02-pad.md", "# Pad\n\n" + "x" * extra_bytes + "\n")


def test_the_budget_is_inclusive_at_exactly_30_kib_and_exclusive_one_byte_over(repo: Path) -> None:
    padded_repo(repo, 1)
    base = len(sync_agents.build_outputs(repo)["AGENTS.md"].encode("utf-8"))
    limit = int(sync_agents.BUDGET_KIB * 1024)

    padded_repo(repo, limit - base + 1)
    exact = sync_agents.build_outputs(repo)["AGENTS.md"]
    assert len(exact.encode("utf-8")) == limit
    assert run(repo) == 0

    padded_repo(repo, limit - base + 2)
    assert run(repo, "--check") == 1


def test_the_budget_error_names_the_size_and_the_remedy(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    padded_repo(repo, 40_000)

    assert run(repo) == 1
    err = capsys.readouterr().err
    assert "budget is 30 KiB" in err
    assert "tier: extended" in err
    assert not (repo / "AGENTS.md").exists()


def test_marking_a_big_module_extended_brings_the_file_under_budget(repo: Path) -> None:
    write(
        repo / ".ai/universal/02-pad.md",
        "# Pad\n<!-- tier: extended -->\n> **Essence.** Big.\n\n" + "x" * 40_000 + "\n",
    )

    assert run(repo) == 0
    assert len((repo / "AGENTS.md").read_bytes()) < 30 * 1024


def test_multibyte_text_is_measured_in_bytes_not_characters(repo: Path) -> None:
    write(repo / ".ai/universal/02-pad.md", "# Pad\n\n" + "\u00e9" * 16_000 + "\n")

    assert run(repo) == 1


# ------------------------------ main: write vs check


def test_check_never_writes_anything(repo: Path) -> None:
    before = snapshot(repo)

    assert run(repo, "--check") == 1

    assert snapshot(repo) == before


def test_check_lists_every_missing_and_stale_file(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(repo)
    write(repo / ".codex/agents/ghost.toml", "x")
    write(repo / ".codex/skills/ghost/SKILL.md", "x")
    (repo / "AGENTS.md").unlink()

    assert run(repo, "--check") == 1

    err = capsys.readouterr().err
    assert "Run: just agents" in err
    for name in ("AGENTS.md", ".codex/agents/ghost.toml", ".codex/skills/ghost/SKILL.md"):
        assert name in err


def test_check_succeeds_with_a_summary_when_in_sync(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(repo)
    capsys.readouterr()

    assert run(repo, "--check") == 0
    out = capsys.readouterr().out
    assert out.startswith("ok  assistants in sync (AGENTS.md ")
    assert "2 mirrored files" in out


def test_write_reports_counts_and_the_second_run_changes_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repo) == 0
    assert "synced 3, removed 0" in capsys.readouterr().out
    first = snapshot(repo)

    assert run(repo) == 0
    assert "synced 0, removed 0" in capsys.readouterr().out
    assert snapshot(repo) == first


def test_hand_edits_to_generated_files_are_detected_and_reverted(repo: Path) -> None:
    run(repo)
    genuine = snapshot(repo)
    for rel in ("AGENTS.md", ".codex/agents/demo-agent.toml", ".codex/skills/demo-skill/SKILL.md"):
        target = repo / rel
        target.write_bytes(target.read_bytes() + b"tampered\n")
        assert run(repo, "--check") == 1
        assert run(repo) == 0
        assert snapshot(repo) == genuine


def test_a_missing_generated_file_is_recreated(repo: Path) -> None:
    run(repo)
    (repo / ".codex/agents/demo-agent.toml").unlink()

    assert run(repo, "--check") == 1
    assert run(repo) == 0
    assert (repo / ".codex/agents/demo-agent.toml").is_file()


def test_generated_files_are_written_with_lf_even_on_windows(repo: Path) -> None:
    run(repo)

    for rel, data in snapshot(repo).items():
        if rel.startswith((".codex", "AGENTS")):
            assert b"\r\n" not in data, rel


def test_crlf_checkouts_of_sources_and_outputs_count_as_in_sync(repo: Path) -> None:
    run(repo)

    for path in repo.rglob("*"):
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert run(repo, "--check") == 0


def test_crlf_sources_produce_the_same_outputs_as_lf_sources(repo: Path) -> None:
    lf_outputs = sync_agents.build_outputs(repo)
    for path in repo.rglob("*.md"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert sync_agents.build_outputs(repo) == lf_outputs


def test_renaming_an_agent_removes_the_old_mirror(repo: Path) -> None:
    run(repo)
    write(repo / ".claude/agents/demo-agent.md", AGENT.replace("demo-agent", "renamed-agent"))

    assert run(repo) == 0

    assert not (repo / ".codex/agents/demo-agent.toml").exists()
    assert (repo / ".codex/agents/renamed-agent.toml").is_file()
    assert run(repo, "--check") == 0


def test_deleting_a_skill_removes_its_mirror_folder_contents(repo: Path) -> None:
    run(repo)
    write(repo / ".codex/skills/demo-skill/extra.md", "stale extra")
    (repo / ".claude/skills/demo-skill/SKILL.md").unlink()
    (repo / ".claude/skills/demo-skill").rmdir()

    assert run(repo) == 0

    assert not list((repo / ".codex/skills").rglob("*.md"))
    assert run(repo, "--check") == 0


def test_files_outside_the_generated_folders_are_never_removed(repo: Path) -> None:
    write(repo / ".codex/config.toml", "keep me")
    write(repo / "notes.md", "keep me too")

    run(repo)

    assert (repo / ".codex/config.toml").read_text(encoding="utf-8") == "keep me"
    assert (repo / "notes.md").is_file()
    assert run(repo, "--check") == 0


def test_universal_modules_come_before_project_modules_each_sorted_by_name(repo: Path) -> None:
    write(repo / ".ai/universal/00-first.md", "# First\n")
    write(repo / ".ai/project/05-early.md", "# Early\n")

    run(repo)

    paths = [
        line
        for line in (repo / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("<!-- module: ")
    ]
    assert paths == [
        "<!-- module: .ai/universal/00-first.md -->",
        "<!-- module: .ai/universal/01-alpha.md -->",
        "<!-- module: .ai/project/05-early.md -->",
        "<!-- module: .ai/project/10-beta.md -->",
    ]
