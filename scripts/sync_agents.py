"""Keep every AI assistant on one rule set.

Sources of truth:
    .ai/universal/*.md, .ai/project/*.md   rule modules (CLAUDE.md imports them natively)
    .claude/agents/*.md                     project subagents
    .claude/skills/<name>/SKILL.md          project skills
Generated here (never edit by hand):
    AGENTS.md                               rule modules assembled for Codex and other tools
    .codex/agents/<name>.toml               Codex mirror of .claude/agents
    .codex/skills/<name>/SKILL.md           Codex mirror of .claude/skills

Usage: uv run python scripts/sync_agents.py [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Codex reads at most 32 KiB of project instructions; failing here names the problem
# instead of letting rules be truncated silently.
BUDGET_KIB = 30.0
TIER_MARKER = "tier: extended"
ESSENCE_PREFIX = "> **Essence.**"
GROUPS = ("universal", "project")
GENERATED_DIRS = (".codex/agents", ".codex/skills")
SYNC_COMMAND = "just agents"

BANNER = f"""<!--
GENERATED FILE - DO NOT EDIT.
Source of truth: .ai/universal/*.md and .ai/project/*.md.
Edit a module, then run: {SYNC_COMMAND}
-->

# ChatImport - working notes for Codex and other AI assistants

This file is the entry point for Codex and any tool that reads AGENTS.md. It is assembled
from the shared rule modules in `.ai/`, so every assistant follows identical rules. Later
sections override earlier ones; an explicit owner instruction in the current conversation
overrides everything. Start every task with the orientation ritual in the progress module."""

EXTENDED_INDEX_HEADER = (
    "<!-- module index: extended -->\n\n"
    "# Modules loaded on demand\n\n"
    "These rules bind exactly like the inlined ones; only their full text lives\n"
    "outside this file, to stay within the instruction budget. Read the file itself\n"
    "when a task touches it — that is an obligation, not a suggestion.\n"
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class Module:
    path: str
    body: str

    @property
    def is_extended(self) -> bool:
        return any(TIER_MARKER in line for line in self.body.splitlines()[:5])

    @property
    def title(self) -> str:
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "(untitled module)"

    @property
    def essence(self) -> str | None:
        for line in self.body.splitlines():
            stripped = line.strip()
            if stripped.startswith(ESSENCE_PREFIX):
                return stripped[len(ESSENCE_PREFIX) :].strip()
        return None


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def collect_modules(root: Path) -> list[Module]:
    modules: list[Module] = []
    for group in GROUPS:
        directory = root / ".ai" / group
        if not directory.is_dir():
            raise SyncError(f"missing module directory: {directory}")
        for path in sorted(directory.glob("*.md"), key=lambda p: p.name):
            modules.append(Module(f".ai/{group}/{path.name}", read(path).strip()))
    if not modules:
        raise SyncError("no rule modules found under .ai/")
    return modules


def render_agents_md(modules: list[Module]) -> str:
    sections = [BANNER]
    sections += [f"<!-- module: {m.path} -->\n\n{m.body}" for m in modules if not m.is_extended]
    extended = [m for m in modules if m.is_extended]
    if extended:
        index = EXTENDED_INDEX_HEADER
        for m in extended:
            index += f"\n## {m.title}\n\nFile: `{m.path}`\n"
            if m.essence:
                index += f"\n{m.essence}\n"
        sections.append(index.rstrip())
    return "\n\n---\n\n".join(sections) + "\n"


def parse_frontmatter(text: str, name: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        raise SyncError(f"{name}: missing --- frontmatter ---")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    for key in ("name", "description"):
        if not meta.get(key):
            raise SyncError(f"{name}: frontmatter needs `{key}`")
    return meta, match.group(2).strip()


def render_codex_agent(source_name: str, text: str) -> tuple[str, str]:
    meta, body = parse_frontmatter(text, source_name)
    if "'''" in body:
        raise SyncError(f"{source_name}: body must not contain '''")
    content = "\n".join(
        [
            f"# GENERATED from .claude/agents/{source_name} by {SYNC_COMMAND} - do not edit.",
            f"name = {json.dumps(meta['name'], ensure_ascii=False)}",
            f"description = {json.dumps(meta['description'], ensure_ascii=False)}",
            f"model_reasoning_effort = {json.dumps(meta.get('effort', 'high'))}",
            "developer_instructions = '''",
            body,
            "'''",
            "",
        ]
    )
    return f".codex/agents/{meta['name']}.toml", content


def render_codex_skill(skill: str, text: str) -> tuple[str, str]:
    parse_frontmatter(text, f"{skill}/SKILL.md")
    marker = f"# GENERATED from .claude/skills/{skill}/SKILL.md by {SYNC_COMMAND} - do not edit.\n"
    return f".codex/skills/{skill}/SKILL.md", text.replace("---\n", "---\n" + marker, 1)


def build_outputs(root: Path) -> dict[str, str]:
    outputs = {"AGENTS.md": render_agents_md(collect_modules(root))}
    for path in sorted((root / ".claude" / "agents").glob("*.md")):
        target, content = render_codex_agent(path.name, read(path))
        outputs[target] = content
    for skill_dir in sorted(p for p in (root / ".claude" / "skills").iterdir() if p.is_dir()):
        target, content = render_codex_skill(skill_dir.name, read(skill_dir / "SKILL.md"))
        outputs[target] = content
    return outputs


def size_kib(text: str) -> float:
    return len(text.encode("utf-8")) / 1024


def plan(root: Path, outputs: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (paths whose content differs, generated paths that no longer have a source)."""
    changed = [
        rel
        for rel, content in outputs.items()
        if not (root / rel).is_file() or read(root / rel) != content
    ]
    existing = [
        p.relative_to(root).as_posix()
        for directory in GENERATED_DIRS
        if (root / directory).is_dir()
        for p in (root / directory).rglob("*")
        if p.is_file()
    ]
    stale = sorted(rel for rel in existing if rel not in outputs)
    return changed, stale


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Regenerate or verify AGENTS.md and .codex/.")
    parser.add_argument("--check", action="store_true", help="fail instead of rewriting")
    args = parser.parse_args(argv)

    try:
        outputs = build_outputs(root)
    except SyncError as error:
        sys.stderr.write(f"ERR {error}\n")
        return 1

    kib = size_kib(outputs["AGENTS.md"])
    if kib > BUDGET_KIB:
        sys.stderr.write(
            f"ERR AGENTS.md would be {kib:.1f} KiB; the budget is {BUDGET_KIB:.0f} KiB. "
            "Tighten a module, or mark a situational one `<!-- tier: extended -->` "
            "with a `> **Essence.**` line.\n"
        )
        return 1

    changed, stale = plan(root, outputs)
    summary = f"AGENTS.md {kib:.1f} of {BUDGET_KIB:.0f} KiB, {len(outputs) - 1} mirrored files"
    if args.check:
        if changed or stale:
            listing = "\n  ".join([*changed, *stale])
            sys.stderr.write(
                f"ERR assistant files are out of sync. Run: {SYNC_COMMAND}\n  {listing}\n"
            )
            return 1
        sys.stdout.write(f"ok  assistants in sync ({summary})\n")
        return 0

    for rel in stale:
        (root / rel).unlink()
    for rel in changed:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(outputs[rel], encoding="utf-8", newline="\n")
    sys.stdout.write(f"ok  synced {len(changed)}, removed {len(stale)} ({summary})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
