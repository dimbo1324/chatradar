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

+ A: Desktop export parser and mapper, Telethon mapper and connector, JSONL raw store
    with a chat catalog, import and sync services, synthetic fixtures (branch
    `claude/mvp-connectors-0596b3`, 183 tests in the branch)
+ B: engine with pragmas and programmatic migrations, `SqlRepository`, FTS5 index
    (`claude/mvp-storage-0890e9`, 94 integration tests)
+ C: noise, enrich, threads, index stages, runner, registry, lexicons, process service
    (`claude/mvp-pipeline-d26ace`)
+ D: JSON API per `docs/api.md`, static SPA with six pages, CSP
    (`claude/mvp-web-305522`, checked in a browser by the session)

## 3. Wave 2 — integration (lead)

+ Merge A, B, C, D into `feat/mvp` (no conflicts; 470 tests green after the merges)
+ `services/container.py`, `services/rebuild.py`, `services/worker.py`, CLI wiring;
  `ChatCatalog` and `DerivedDataStore` added to the ports
+ Integration defects found and fixed: `SqlRepository` parameter names did not match the
  ports; a cached structlog logger wrote to a closed stream; `process` turned any
  `ValueError` into "unknown stage"
+ Docker image built and run: import into a volume, process, web panel and API, version
  bumps reindex existing data
- `docker compose up` itself was not run (the image and both commands were run directly)
+ End-to-end on synthetic data: import → process → search → rebuild → web API (test), and
  every page checked in the browser against the Docker container
+ Fixes from the manual check: Cyrillic yo/ie in search (index v2), "thanks for sharing"
  as gratitude (noise v2)
- Live Telegram login and sync: not run — synthetic data only (owner decision); the
  owner's next step
- CI on GitHub for `4c48369`: result unknown — the anonymous API rate limit was spent

## 4. Completion

+ `docs/ROADMAP.md` status lines for steps 2–8, project map, command reference, README,
  CHANGELOG, `.ai/CHANGELOG.md`
+ `just check` green
- Fast-forward of `main` and push: not done — waits for the owner
+ Final report to the owner
