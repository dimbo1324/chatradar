# Decisions and Open Questions

Owner decisions that constrain future work, and questions still open. Newest first. A
decision made in chat is recorded here, or it is invisible to the next session.

## Decisions

### 2026-10-19 — MVP scope and how it is built

- **Scope:** roadmap steps 2–8, without AI (the complete non-AI service of
  `docs/architecture.md`). AI answers, digests and the Telegram bot come later.
- **Parallel development:** the lead fixes the contracts first (`domain/models.py`,
  `domain/ports.py`, `pipeline/base.py`, `storage/db/tables.py` with migration 0001,
  `services/normalize.py`, `services/queries.py`, `docs/api.md`), then separate agent
  sessions build connectors, storage, pipeline and web in their own git worktrees with
  disjoint file zones; the lead merges them into `feat/mvp` and integrates. This
  overrides the one-step-per-task order of `docs/ROADMAP.md` for steps 2–8.
- **Frontend:** plain HTML, CSS and JavaScript modules over a JSON API, no build step
  (ADR-0002). Jinja2 and HTMX are dropped.
- **Data:** agents use only synthetic anonymized fixtures; Telethon is tested with fakes.
  The owner does the first live Telegram login after the MVP is merged.

### 2026-10-19 — Everything in the repository is English

Code, comments, docstrings, CLI help, documentation, rule modules, commit messages and test
names are English. Enforced by `scripts/check_language.py` in `just check`, pre-commit and
CI. Russian and Spanish appear only as data (anonymized fixtures, lexicons) in the allowed
paths. Reports to the owner in chat stay Russian.

### 2026-10-19 — AI assistant rule system, Claude Code first

Rules in `.ai/` shared by every assistant; `CLAUDE.md` imports them, `AGENTS.md` and
`.codex/` are generated, `GEMINI.md` imports `AGENTS.md`. Same layout as the owner's
`daily-quest`, `codepack` and `CogniBoiler`.

### 2026-10-19 — Publishing without pull requests

Task branch → green `just check` → `git merge --ff-only` into `main` → `git push origin
main`, only when the owner asked in the current task. Adopted from the owner's other
repositories; tell the agent if this project should use pull requests instead.

### 2026-10-19 — MIT license

The repository is public under MIT.

### 2026-10-18 — Architecture

Modular monolith with ports and adapters, immutable raw JSONL, versioned idempotent
stages, SQLite first and Postgres later, no AI until the non-AI service works
(`docs/adr/0001-modular-monolith-hexagonal.md`, `docs/architecture.md`).

## Open questions

- Project name (ChatRadar is a working title).
- Exact data schema: message, thread, topic, source.
- Grouping messages into threads without replies.
- Which AI models for labelling and for answers, and how to keep costs low.
- How to measure answer quality.
- Solo or with a partner; who owns what.
