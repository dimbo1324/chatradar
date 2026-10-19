# Codex Project Configuration

Project-scoped Codex configuration for ChatRadar.

Rules live in the shared modules under `.ai/`. Codex reads them through the generated
`AGENTS.md` in the repository root. Claude Code (the priority assistant) gets the same
rules through `CLAUDE.md`; Gemini CLI through `GEMINI.md`.

## Files

- `config.toml` — project-scoped defaults. No secrets; personal overrides go to the
  git-ignored `config.local.toml`.
- `agents/` — **generated** from `.claude/agents/` by `just agents`.
- `skills/` — **generated** from `.claude/skills/` by `just agents`.

Never edit `agents/`, `skills/` or `AGENTS.md` by hand: edit the source in `.ai/` or
`.claude/` and run `just agents`. `just check` and CI fail while they are out of sync.

## Agents

`chatradar-step-planner`, `chatradar-connectors`, `chatradar-pipeline`, `chatradar-storage`,
`chatradar-interfaces`, `chatradar-platform`, `chatradar-privacy-security`,
`chatradar-quality-reviewer`, `chatradar-repo-maintainer`.

## Skills

`step-episode`, `pipeline-stage-change`, `schema-change`, `code-review`, `ci-fix`,
`project-maintenance`, `rules-evolution`.
