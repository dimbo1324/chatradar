# ChatRadar — Roadmap

The plan and the progress record. Steps run in order; **the first step without a
`**Status.**` line is next**. Skipping ahead needs an owner decision in `docs/decisions.md`.
Design details for every step: `docs/architecture.md` §12.

## 1. Overview

| Step | What | Result | Status |
|---|---|---|---|
| 1 | Skeleton: uv, ruff, pyright, pytest, pre-commit, CI, `Settings` | Empty project passing CI | done 2026-10-19 |
| 2 | Domain and ports; Telegram Desktop JSON import; JSONL `RawStore` | Data in `data/raw/` without Telethon | done 2026-10-19 |
| 3 | SQLAlchemy, Alembic, tables, normalization with upsert | Messages in SQLite | done 2026-10-19 |
| 4 | Stage runner; noise filter and enrichment with tests | Labelled messages | done 2026-10-19 |
| 5 | Web: chats, pipeline, messages pages | Visible internals | done 2026-10-19 |
| 6 | Thread grouping, FTS5, search page | Working search | done 2026-10-19 |
| 7 | Telethon connector, `login`, `sync`, worker | Automatic incremental sync | code done 2026-10-19; live login pending |
| 8 | Docker and Compose for the whole service | `docker compose up` runs everything | done 2026-10-19 (image verified) |

After step 8 ChatRadar is a complete service without AI. Beside the numbered steps the
learning lexicon (see the section after step 8) adds the measurement and review loop the
AI stages will plug into.

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

**Status.** Done 2026-10-19 (package A): Desktop export parser (single chat and full account)
and mapper, append-only `JsonlRawStore` with a chat catalog beside the raw data,
`chatradar import tg-export` (then processes), synthetic ru/es fixtures (60 messages).

### Step 3 — Database and normalization

SQLAlchemy 2.0 tables (`chats`, `sync_state`, `messages`, `threads`, `messages_fts`), the
first Alembic migration, the normalize stage (pure mapper, NFC text, UTC dates, links) with
hash-checked upsert, `chatradar rebuild`.

**Status.** Done 2026-10-19 (package B + lead): engine with SQLite pragmas, migrations on
start, `SqlRepository` (chat, message and query ports), `chatradar rebuild` clears
derived data and re-maps every raw record; verified to reproduce the same counts.

### Step 4 — Runner, noise, enrichment

The stage runner over `<stage>_v` columns, noise rules with table-driven tests, enrichment
(`lang`, `is_question`, `urls`, `has_mention`), `chatradar process`.

**Status.** Done 2026-10-19 (package C): noise rules (service, sticker, emoji, gratitude,
short, duplicate, spam) from ru/es/en lexicons, enrichment with lingua, runner with
versions; noise is at version 2 after a miss found on the review page.

### Step 5 — Web panel

JSON API (`docs/api.md`) and a static panel in plain HTML, CSS and JavaScript (ADR-0002):
chats, pipeline state, message table, thread view, filter review page.

**Status.** Done 2026-10-19 (package D): every endpoint of `docs/api.md`, six pages in native
ES modules, strict CSP, text inserted only through DOM nodes; checked in a browser
against a real database inside the Docker image.

### Step 6 — Threads and search

Reply components plus time-gap grouping, stable thread ids, FTS5 index, search page.

**Status.** Done 2026-10-19 (packages B, C): union-find over replies plus a 30-minute gap,
incremental window, FTS5 with prefix terms for inflection and yo/ie folding (index
version 2). Cross-language search ("rent" finding "alquiler") is level 1: embeddings.

### Step 7 — Telethon and worker

Telethon connector with FloodWait handling, `telegram login`, `chats add`, `sync`, recheck
of the last N days, the `worker` loop with `alembic upgrade head` at start.

**Status.** Code done 2026-10-19 (package A + lead): `TelegramConnector`, `telegram login`,
`chats add`, `sync`, the worker loop (migrate, sync, process, sleep; daily recheck; a
failed cycle is retried). Tested with fakes only — **the first live login and sync are
the owner's next step** (`docs/decisions.md`).

### Step 8 — Docker for the whole service

`docker compose up` runs web and worker with real data; login inside the container;
documented upgrade to Postgres.

**Status.** Done 2026-10-19: the image installs the wheel with the static panel and the
lexicons; verified by building it, importing the fixture into a volume, reindexing
after version bumps and browsing the panel. `docker compose up` itself was not run in
this session.

## 3. Learning lexicon (2026-10-19)

Decisions: `docs/adr/0003-learning-lexicon.md`, `docs/adr/0004-panel-write-path.md`. Deferred
parts: `docs/backlog.md`.

**Status.** Done 2026-10-19: (1) measurement — the generator writes ground truth, `chatradar
eval` computes precision/recall/F1 against it or against human labels, with a regression gate in
the tests; (2) the lexicon is data (`lexicon_terms`, seeded from the built-in lists, revisioned,
stages reprocess when their applied revision is behind); (3) candidate mining by log-odds with
thresholds on occurrences, chats and authors (`chatradar mine`), dormancy for long-unseen mined
terms; (4) human decisions and labels from the panel (pages Lexicon and Quality, buttons on
the filter review and thread pages) through a guarded write path. The panel was redesigned: design
system with light/dark themes, Inter font, drawn SVG icons, responsive layout. Not yet: AI as a
proposer and judge, stemming, per-chat weights, topic terms, worker wake-up on a decision.
