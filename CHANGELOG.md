# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added

- AI assistant rule system: `.ai/` modules shared by Claude Code (`CLAUDE.md`), Codex
  (generated `AGENTS.md`, `.codex/`) and Gemini CLI (`GEMINI.md`); project subagents and
  skills in `.claude/`.
- `scripts/sync_agents.py`, `scripts/check_language.py`, `scripts/doctor.py`; `just check`
  runs the agents-sync and language checks; state documents `docs/ROADMAP.md`,
  `docs/decisions.md`, `task-checklist.md`.
- Project skeleton: uv, ruff, pyright strict, pytest, pre-commit, gitleaks.
- MIT license.
- `Settings` on pydantic-settings, structlog, the domain `Message` model and ports.
- Typer CLI with the planned commands (stubs for now), a web stub with `/healthz`.
- Alembic (async, batch mode on SQLite).
- Dockerfile (multi-stage, uv, non-root), compose.yaml, justfile.
- GitHub Actions: CI (lint, typecheck, tests on Linux and Windows, Docker smoke), CodeQL,
  image release to GHCR on tags; Dependabot.

### Changed

- Everything in the repository is English.

### Fixed

- The Docker build includes `LICENSE`, which `uv_build` needs.
