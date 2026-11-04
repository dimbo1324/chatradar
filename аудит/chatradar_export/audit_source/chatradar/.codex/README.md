# Codex Project Configuration

Project-scoped Codex configuration for ChatImport.

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

`chatimport-step-planner`, `chatimport-telegram`, `chatimport-storage`,
`chatimport-interfaces`, `chatimport-platform`, `chatimport-privacy-security`,
`chatimport-quality-reviewer`, `chatimport-repo-maintainer`.

## Skills

`step-episode`, `format-change`, `code-review`, `ci-fix`, `project-maintenance`,
`rules-evolution`.
