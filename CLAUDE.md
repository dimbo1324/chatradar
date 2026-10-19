# ChatRadar — working notes for Claude Code

This file is the Claude Code entry point. All rules live in shared modules under `.ai/` —
the single source of truth for every AI assistant in this repository. Codex and other tools
read the same modules through the generated `AGENTS.md`; never edit that file by hand (edit
a module, then run `just agents`).

Later modules override earlier ones; an explicit owner instruction in the current
conversation overrides everything.

## Starting a fresh session

Sessions often begin with no context. Before any work, run the **orientation ritual** from
`@.ai/project/13-progress-tracking.md`: git status and log → `docs/ROADMAP.md` (the first
step without a `**Status.**` line is next) → `task-checklist.md` → `docs/decisions.md` →
the matching section of `docs/architecture.md`.

The product intent is in `docs/vision.md`; the step-by-step design in `docs/architecture.md`.

**One gate for everything:** `just check` (ruff, pyright strict, pytest, agents sync,
language). CI runs the same sections. Toolchain problems: `just doctor`. Details:
`@.ai/project/11-commands.md`.

**Talking to the owner:** answers in Russian, short and step by step; say honestly when an
idea is weak; do not over-engineer early. Everything committed to the repository is English.

The rules are meant to evolve: see `@.ai/universal/08-rules-evolution.md` for when and how to
change them, and `.ai/CHANGELOG.md` for what changed so far.

## Universal rules (portable to any project)

- @.ai/universal/01-workflow.md
- @.ai/universal/02-task-checklist.md
- @.ai/universal/03-scope-and-code-style.md
- @.ai/universal/04-architecture-boundaries.md
- @.ai/universal/05-security-and-secrets.md
- @.ai/universal/06-quality-and-testing.md
- @.ai/universal/07-multi-assistant.md
- @.ai/universal/08-rules-evolution.md
- @.ai/universal/09-time-and-timestamps.md

## Project rules (ChatRadar)

- @.ai/project/10-project-map.md
- @.ai/project/11-commands.md
- @.ai/project/12-domain-rules.md
- @.ai/project/13-progress-tracking.md
- @.ai/project/14-command-reference.md

## Claude Code workspace

- `.claude/settings.json` — permission allow and deny lists (secrets are never read).
- `.claude/launch.json` — the debug panel for the preview browser.
- `.claude/agents/` — project subagents (`chatradar-*`); the source of the generated
  `.codex/agents/` mirror.
- `.claude/skills/` — reusable workflows (`step-episode`, `pipeline-stage-change`,
  `schema-change`, `code-review`, `ci-fix`, `project-maintenance`, `rules-evolution`);
  the source of `.codex/skills/`.
