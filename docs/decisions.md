# Decisions and Open Questions

Owner decisions that constrain future work, and questions still open. Newest first. A
decision made in chat is recorded here, or it is invisible to the next session.

## Decisions

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
