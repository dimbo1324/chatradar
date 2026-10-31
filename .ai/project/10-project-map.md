# Project: ChatImport

ChatImport is a background service that keeps a full local text archive of the Telegram
groups and channels listed in the owner's `chats.toml` library. It runs as its own session
of the owner's account (Telethon, MTProto), backfills each chat's history once, then appends
new messages in small batches (every 5 messages or 30 seconds), rechecks the last 7 days
daily for edits and deletions, and protects free disk space by trimming the oldest parts.
Output is JSONL in a `ChatImport` folder (the Desktop by default). Product intent:
`docs/vision.md`; design: `docs/architecture.md`.

This is branch `chatimport`, a parallel line to ChatRadar on `main`. The two are meant to
become one product later (`docs/architecture.md` §15): ChatImport's JSONL folder is a
candidate raw store for ChatRadar.

**Stage: 0.1-0.7 implemented and hardened (2026-10-30); the owner's live check with a real
account is next, then 1.0 (ChatRadar integration).**

## Repository map

Single uv project on Python 3.14+ (`src/` layout, package `chatimport`). `src/chatimport/`:

- **Core:** `config` (TOML to dataclasses), `config_edit` (writes `output.root_dir`),
  `toml_edit` (comment-keeping line edits), `paths` (app folders, data root, OneDrive check),
  `records` (record types, JSONL lines), `ports` (gateway, clock, disk protocols, errors),
  `runtime` (chat handles, registry, notifier, `BackfillSlots`), `textnorm` (`fold`,
  `transliterate`), `refs` (the one ref parser), `logging_setup` (rotating file log).
- **Library:** `library` (`chats.toml` parse, diff, watch, add/enable), `resolution` (entries
  to chats, error book), `offline` (CLI work without the service: trim, floor, selector).
- **Service:** `app` (facade: run, run --once, library loop, set-root), `context` (config,
  folders, gateway), `service_runtime` (everything on one data root), `supervisor`
  (restarts with backoff), `router` (events to workers, `_unrouted_deletes.jsonl`),
  `commands` (command registry), `control` (control folder, instance lock), `status`
  (`_status.json`), `recheck` (daily comparison and scheduler).
- **Worker:** `worker` (`ChatWorker` facade), `worker_signals` (flags), `worker_live` and
  `worker_buffer` (live intake), `worker_backfill` (head and tail), `worker_store` (folder
  access, threads), `flood` (FloodWait).
- **Maintenance:** `trim`, `media` (downloader), `integrity` (`check`), `export`
  (`export-json`), `setroot`, `guards/disk` (disk guard, media gate), `guards/folders`.
- **Storage:** `layout`, `state`, `writer`, `reader`, `recover`, `fileio` (atomic and
  retried file primitives), `chat_store` (one chat folder), `month_commit` (journalled
  month rewrite), `media_files` (media names, safe extensions).
- **Telegram (only Telethon user):** `client` (gateway, login), `resolve`, `mapper` (pure).
- **Interfaces:** `cli` (entry point) with `cli_support`, `cli_chats`, `cli_service`,
  `cli_data`; `tray` with `tray_dialogs`; `__main__`.

Elsewhere:

- `config.example.toml`, `chats.example.toml` — templates; the real files live in the
  application data folder and are never tracked.
- `tests/unit/<area>`, `tests/integration`, `tests/fakes.py` (clock, disk, scripted gateway);
  `tests/fixtures/` is reserved for anonymized data and does not exist yet.
- `scripts/` — stdlib-only repo tooling: `sync_agents.py`, `check_language.py`, `doctor.py`.
- `justfile`, `.pre-commit-config.yaml`, `.github/`.
- `docs/` — `vision.md`, `architecture.md` (§12 lists every module), `ROADMAP.md`,
  `decisions.md`, `backlog.md`, `adr/`.
- `.ai/`, `.claude/`, `.codex/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` — assistant rules.

## Language policy

- **Everything tracked by git is English**: code, comments, docstrings, CLI help, docs, rule
  modules, commit messages, test names, `task-checklist.md`. Owner decision 2026-10-19.
- `python scripts/check_language.py` fails on any Cyrillic character in a tracked file,
  except under `tests/fixtures/` (anonymized chat data is Russian by nature).
- The owner's original spec is Russian and lives outside the repository;
  `docs/architecture.md` is its English version and the reference inside the repository.
- Reports to the owner in chat are in Russian, short and step by step.

## Documentation policy

- `docs/vision.md` changes only when the product intent changes, by owner agreement.
- `docs/ROADMAP.md` is the plan and progress record; `docs/decisions.md` the decision log.
- The no-new-docs exception (`03-scope-and-code-style.md`) covers `README.md`, `docs/` and
  `CHANGELOG.md`.

## Product guardrails

- Only chats listed and enabled in `chats.toml` are read or stored; private dialogs, bots
  and everything else are dropped at the router.
- The service never joins a chat by itself and never sends anything to Telegram.
- Data stays on the owner's disk. Sender names are personal data (Uruguay, Ley 18.331):
  any export or publication strips them.
- Telegram is read through the owner's user account with pauses and FloodWait respected;
  history backfill runs one chat at a time.
- **Stage order in `docs/ROADMAP.md` is binding.** Skipping ahead needs an owner decision
  recorded in `docs/decisions.md`.
