# Task: MVP without AI — roadmap steps 2–8, built by parallel agent sessions

Owner instruction of 2026-10-19: build the MVP with a multi-agent setup; frontend in plain
JavaScript, CSS and HTML; ask questions first. Owner answers: steps 2–8 without AI;
parallel sessions in git worktrees; static frontend over a JSON API; synthetic data only
(`docs/decisions.md`, 2026-10-19).

Synchronisation: integration branch `feat/mvp`. Wave 0 — the lead commits the contracts.
Wave 1 — one session and one branch per work package, disjoint file zones, no dependency
changes (`pyproject.toml` and `uv.lock` belong to the lead). Wave 2 — the lead merges each
branch into `feat/mvp`, runs the gate after each merge, wires services, CLI, worker and
Docker, and runs the end-to-end check.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Wave 0 — contracts (lead)

+ Owner decisions recorded; ADR-0002 (static frontend); `jinja2` removed
+ `domain/models.py`, `domain/ports.py`, `domain/text.py`
+ `pipeline/base.py` (`Stage`, `STAGE_ORDER`, `STAGE_COLUMNS`, `NORMALIZE_VERSION`)
+ `storage/db/tables.py`, migration 0001 (with `threads_fts`), `migrations/env.py`
+ `services/normalize.py`, `services/queries.py`, `docs/api.md`
+ Contract tests; `just check` green; committed on `feat/mvp`

## 2. Wave 1 — work packages (parallel sessions)

File zones (a package touches nothing outside its zone; tests live in its test folder):

| Package | Zone |
|---|---|
| A connectors | `src/chatradar/connectors/**`, `src/chatradar/storage/raw_jsonl.py`, `src/chatradar/services/ingest.py`, `src/chatradar/services/sync.py`, `tests/unit/connectors/**`, `tests/fixtures/tg_export/**` |
| B storage | `src/chatradar/storage/db/**` except `tables.py`, `tests/integration/storage/**` |
| C pipeline | `src/chatradar/pipeline/**` except `base.py`, `src/chatradar/resources/lexicons/**`, `src/chatradar/services/process.py`, `tests/unit/pipeline/**`, `tests/fixtures/pipeline/**` |
| D web | `src/chatradar/web/**`, `tests/unit/web/**`, `tests/unit/test_web.py` |

[ ] A: Telegram Desktop export parser and mapper, Telethon mapper and connector, JSONL raw
    store, import and sync services, synthetic export fixtures
[ ] B: async engine with SQLite pragmas, SQL repositories (chat, message, query), FTS5
    search index
[ ] C: noise, enrich, threads, index stages, the runner, lexicons, process service
[ ] D: JSON API per `docs/api.md`, static SPA (chats, pipeline, messages, thread, search,
    review)

## 3. Wave 2 — integration (lead)

[ ] Merge A, B, C, D into `feat/mvp`, gate green after each merge
[ ] `services/container.py`, rebuild service, CLI wiring, worker loop with migrations
[ ] Docker image serves static files; compose runs web and worker
[ ] End-to-end on synthetic data: import → process → search → web pages

## 4. Completion

[ ] `docs/ROADMAP.md` status lines for steps 2–8, project map, README, CHANGELOG
[ ] `just check` green; fast-forward `main` only when the owner says so
[ ] Final report to the owner
