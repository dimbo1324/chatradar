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

**Stage: 0.0 — repository prepared, no service code yet; stage 0.1 is next.**

## Repository map

Single uv project on Python 3.14+ (`src/` layout, package `chatimport`):

- `src/chatimport/cli.py` — Typer entry point `chatimport`; thin wrappers only.
- Planned modules (spec layout, `docs/architecture.md` §12): `config.py`, `paths.py`,
  `library.py`, `app.py`, `telegram/` (`client.py`, `resolve.py`, `mapper.py`),
  `storage/` (`layout.py`, `writer.py`, `state.py`, `recover.py`), `worker.py`,
  `recheck.py`, `trim.py`, `guards/` (`disk.py`, `folders.py`), `control.py`, `tray.py`,
  `media.py`. A module joins this list when it exists.
- `config.example.toml`, `chats.example.toml` — templates; the real files live in the
  application data folder and are never tracked.
- `tests/unit`, `tests/integration`, `tests/fixtures` (anonymized data only).
- `scripts/` — stdlib-only repo tooling: `sync_agents.py`, `check_language.py`, `doctor.py`.
- `justfile`, `.pre-commit-config.yaml`, `.github/`.
- `docs/` — `vision.md`, `architecture.md`, `ROADMAP.md`, `decisions.md`.
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
