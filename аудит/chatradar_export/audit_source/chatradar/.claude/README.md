# Claude Code Project Configuration

Project-scoped Claude Code configuration for ChatImport. Claude Code is the priority
assistant; Codex and Gemini CLI read the same rules through `AGENTS.md`.

Durable rules live in the shared modules under `.ai/` (universal + project). `CLAUDE.md`
imports them natively via `@` syntax. Subagents should read `AGENTS.md` — the compiled
single-file ruleset.

## Files

- `settings.json` — allowlist for routine read and verification commands; denylist for
  destructive git operations and for reading `.env` and session files.
- `agents/` — project subagents; the **source** of the generated `.codex/agents/`.
- `skills/` — reusable workflows; the **source** of the generated `.codex/skills/`.
- `settings.local.json` — personal overrides, ignored by git.

After editing an agent or a skill, run `just agents` and commit the regenerated `.codex/`.

## Recommended delegation

Do task-owning work on the main thread; spawn a subagent only for independent work that
does not need the main thread's full context:

- `chatimport-step-planner` — scope a `docs/ROADMAP.md` stage before code.
- `chatimport-telegram` — Telethon client, login, ref resolution, mapper, events, FloodWait.
- `chatimport-storage` — parts, writer, `state.json`, recover, trim, disk guard, folder watcher.
- `chatimport-interfaces` — CLI, control queue, `_status.json`, tray.
- `chatimport-platform` — justfile, CI, toolchain, autostart, packaging.
- `chatimport-privacy-security` — secrets, sessions, sender names, Telegram account safety.
- `chatimport-quality-reviewer` — review a diff before finalizing it.
- `chatimport-repo-maintainer` — state documents, rule sync, publishing.

## Quality shortcuts

```bash
just check
just doctor
just agents-check
```

Push `chatimport` only when the owner explicitly asked for it in the current task.
