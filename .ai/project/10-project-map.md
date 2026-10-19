# Project: ChatRadar

ChatRadar collects messages from messenger chats (Telegram first), filters out noise, groups
replies into discussions and makes them searchable, so a question gets a short answer with
**links to the source messages and their dates**. Later: weekly digests of hot topics,
"evergreen questions", who to ask, topic subscriptions. Product intent: `docs/vision.md`.

**Stage: level 0, step 1 of `docs/ROADMAP.md` is done (skeleton).** AI stages (topic
labelling, embeddings, answers) come after the non-AI service is complete; they plug in as
pipeline stages behind the same `Stage` interface.

## Repository map

Single uv project on Python 3.13+ (`src/` layout, package `chatradar`):

- `src/chatradar/config.py` — `Settings` (pydantic-settings), everything from `CHATRADAR_*` env.
- `src/chatradar/logs.py` — structlog setup: console in dev, JSON in prod.
- `src/chatradar/domain/` — `models.py` (`Message`, `ChatInfo`, `RawRecord`, enums) and
  `ports.py` (`Connector`, `RawStore`, `MessageRepository`, `SearchIndex` protocols).
  Imports nothing from adapters.
- `src/chatradar/connectors/` — `telegram/` (Telethon, MTProto user account) and
  `tg_export/` (Telegram Desktop JSON import). Each yields `RawRecord`s.
- `src/chatradar/storage/` — raw JSONL store (source of truth) and `db/` (SQLAlchemy 2.0,
  repositories, FTS5). The only place with dialect-specific code.
- `src/chatradar/pipeline/` — `base.py` (`Stage` protocol, `STAGE_ORDER`) and the stages
  normalize → noise → enrich → threads → index.
- `src/chatradar/services/` — use cases (sync, process, search, stats).
- `src/chatradar/web/` — FastAPI + Jinja2 + HTMX debug panel (`/healthz` today).
- `src/chatradar/cli.py` — Typer entry point `chatradar`; thin wrappers over `services/`.
- `migrations/` — Alembic (async, batch mode on SQLite); `alembic.ini` stays ASCII-only.
- `tests/unit`, `tests/integration`, `tests/fixtures` (anonymized data only).
- `scripts/` — stdlib-only repo tooling: `sync_agents.py`, `check_language.py`, `doctor.py`.
- `data/` — runtime data (raw JSONL, Telegram sessions, SQLite). **Never tracked.**
- `Dockerfile`, `compose.yaml`, `justfile`, `.pre-commit-config.yaml`, `.github/`.
- `docs/` — `vision.md`, `architecture.md`, `ROADMAP.md`, `decisions.md`, `adr/`.
- `.ai/`, `.claude/`, `.codex/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` — assistant rules.

## Language policy

- **Everything tracked by git is English**: code, comments, docstrings, CLI help, docs, rule
  modules, commit messages, test names, `task-checklist.md`. Owner decision 2026-10-19.
- `python scripts/check_language.py` fails on any Cyrillic character in a tracked file,
  except in the data paths listed in `scripts/check_language.py` (`ALLOWED_PREFIXES`):
  anonymized test fixtures and noise/question lexicons, which are Russian and Spanish by
  nature. Code that uses them stays English.
- Reports to the owner in chat are in Russian, short and step by step.

## Documentation policy

- `docs/vision.md` changes only when the product intent changes, by owner agreement.
- `docs/ROADMAP.md` is the plan and progress record; `docs/decisions.md` the decision log.
- The no-new-docs exception (`03-scope-and-code-style.md`) covers `README.md`, `docs/` and
  `CHANGELOG.md`.

## Product guardrails

- Every statement the product shows a user carries a link to the source message and its
  date. No found messages → "no answer in the chats", never an invented one.
- Raw messages are never published outside the owner's machine — only summaries and links.
- No profiles of people are built (Uruguay, Ley 18.331). A specialist directory, if ever
  built, is opt-in only.
- Telegram is read through a user account with pauses and FloodWait respected; a bot
  cannot see history and is not a substitute.
- **Step order in `docs/ROADMAP.md` is binding.** Skipping ahead needs an owner decision
  recorded in `docs/decisions.md`.
