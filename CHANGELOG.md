# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added

- Synthetic chat exports in Russian, Spanish and English (`just synthetic`, `just demo`),
  generated deterministically and calibrated on aggregate statistics of real chats.
- MVP without AI (roadmap steps 2–8): Telegram Desktop export import, Telethon
  connector with login, tracked chats and incremental sync, append-only JSONL raw store,
  SQLite storage with migrations, noise filter (ru/es/en), enrichment, thread grouping,
  FTS5 search with Russian/Spanish inflection, `rebuild` from raw data, the worker loop,
  and a JSON API with a plain HTML/CSS/JavaScript panel (chats, pipeline, messages,
  threads, search, noise review).
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
- The web panel is a static plain-JavaScript app over a JSON API; Jinja2 is removed
  (ADR-0002).

### Fixed

- Noise filter: repeated short replies ("why?", "yes") are no longer duplicates; spam is
  recognised before duplicates and in English "working from home" offers; more gratitude
  phrases. Existing data is re-checked (noise stage version 3).
- Search matches the Cyrillic yo and ie spellings (index stage version 2).
- The Docker build includes `LICENSE`, which `uv_build` needs.
