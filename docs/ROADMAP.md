# ChatRadar — Roadmap

The plan and the progress record. Steps run in order; **the first step without a
`**Status.**` line is next**. Skipping ahead needs an owner decision in `docs/decisions.md`.
Design details for every step: `docs/architecture.md` §12.

## 1. Overview

| Step | What | Result | Status |
|---|---|---|---|
| 1 | Skeleton: uv, ruff, pyright, pytest, pre-commit, CI, `Settings` | Empty project passing CI | done 2026-10-19 |
| 2 | Domain and ports; Telegram Desktop JSON import; JSONL `RawStore` | Data in `data/raw/` without Telethon | next |
| 3 | SQLAlchemy, Alembic, tables, normalization with upsert | Messages in SQLite | |
| 4 | Stage runner; noise filter and enrichment with tests | Labelled messages | |
| 5 | Web: chats, pipeline, messages pages | Visible internals | |
| 6 | Thread grouping, FTS5, search page | Working search | |
| 7 | Telethon connector, `login`, `sync`, worker | Automatic incremental sync | |
| 8 | Docker and Compose for the whole service | `docker compose up` runs everything | |

After step 8 ChatRadar is a complete service without AI. AI stages (topic labelling,
embeddings, answers with sources, digests) follow as new pipeline stages, then the
Telegram bot — product level 0 in `docs/vision.md`.

## 2. Steps

### Step 1 — Skeleton

uv project on Python 3.13+, `src/` layout, ruff, pyright strict, pytest with coverage,
pre-commit (ruff, pyright, uv-lock, gitleaks, a ban on `.env`/`*.session`/`data/`), `Settings`,
structlog, the domain `Message` model and ports, the Typer CLI with stub commands, a FastAPI
`/healthz`, Alembic, Dockerfile, Compose, justfile, GitHub Actions (CI, CodeQL, release),
Dependabot, the AI-assistant rule system.

**Status.** Done 2026-10-19: skeleton on `main`, CI green on Linux and Windows, AI-assistant
rules in `.ai/`, `.claude/`, `.codex/`, everything in English.

### Step 2 — Domain, Telegram Desktop import, raw store

Import `result.json` from Telegram Desktop through the `Connector` port, write `RawRecord`s
to `data/raw/<source>/<chat_id>/<timestamp>.jsonl` through a `RawStore`, `chatradar import
tg-export`. Anonymized fixtures in `tests/fixtures/`.

### Step 3 — Database and normalization

SQLAlchemy 2.0 tables (`chats`, `sync_state`, `messages`, `threads`, `messages_fts`), the
first Alembic migration, the normalize stage (pure mapper, NFC text, UTC dates, links) with
hash-checked upsert, `chatradar rebuild`.

### Step 4 — Runner, noise, enrichment

The stage runner over `<stage>_v` columns, noise rules with table-driven tests, enrichment
(`lang`, `is_question`, `urls`, `has_mention`), `chatradar process`.

### Step 5 — Web panel

JSON API (`docs/api.md`) and a static panel in plain HTML, CSS and JavaScript (ADR-0002):
chats, pipeline state, message table, thread view, filter review page.

### Step 6 — Threads and search

Reply components plus time-gap grouping, stable thread ids, FTS5 index, search page.

### Step 7 — Telethon and worker

Telethon connector with FloodWait handling, `telegram login`, `chats add`, `sync`, recheck
of the last N days, the `worker` loop with `alembic upgrade head` at start.

### Step 8 — Docker for the whole service

`docker compose up` runs web and worker with real data; login inside the container;
documented upgrade to Postgres.
