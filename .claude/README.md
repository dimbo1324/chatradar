# Claude Code Project Configuration

Project-scoped Claude Code configuration for ChatRadar. Claude Code is the priority
assistant; Codex and Gemini CLI read the same rules through `AGENTS.md`.

Durable rules live in the shared modules under `.ai/` (universal + project). `CLAUDE.md`
imports them natively via `@` syntax. Subagents should read `AGENTS.md` — the compiled
single-file ruleset.

## Files

- `settings.json` — allowlist for routine read and verification commands; denylist for
  destructive git and Docker volume operations and for reading `.env` and session files.
- `launch.json` — the debug panel (`chatradar web`) for the preview browser.
- `agents/` — project subagents; the **source** of the generated `.codex/agents/`.
- `skills/` — reusable workflows; the **source** of the generated `.codex/skills/`.
- `settings.local.json` — personal overrides, ignored by git.

After editing an agent or a skill, run `just agents` and commit the regenerated `.codex/`.

## Recommended delegation

Do task-owning work on the main thread; spawn a subagent only for independent work that
does not need the main thread's full context:

- `chatradar-step-planner` — scope a `docs/ROADMAP.md` step before code.
- `chatradar-connectors` — Telethon, Telegram Desktop export, future WhatsApp/Discord.
- `chatradar-pipeline` — normalize, noise, enrich, threads, index; the stage runner.
- `chatradar-storage` — raw JSONL store, SQLAlchemy, Alembic, FTS5, SQLite → Postgres.
- `chatradar-interfaces` — CLI, FastAPI + HTMX panel, later the Telegram bot.
- `chatradar-platform` — Dockerfile, Compose, CI, release, toolchain.
- `chatradar-privacy-security` — secrets, sessions, personal data, Telegram account safety.
- `chatradar-quality-reviewer` — review a diff before finalizing it.
- `chatradar-repo-maintainer` — state documents, rule sync, publishing.

## Quality shortcuts

```bash
just check
just doctor
just agents-check
```

Push to `main` only when the owner explicitly asked for it in the current task.
