# ChatImport — Roadmap

The plan and the progress record. Stages run in order; **the first stage without a
`**Status.**` line is next**. Skipping ahead needs an owner decision in `docs/decisions.md`.
Design details for every stage: `docs/architecture.md`.

## 1. Overview

| Stage | What | Done when | Status |
|---|---|---|---|
| 0.0 | Repository prepared on branch `chatimport`: stack, tooling, rules, docs | `just check` green on an empty package | done 2026-10-29 |
| 0.1 | Config, `chats.toml` library, `login`, `dialogs`, mapper with sender names, chunked writer, full backfill of one chat | One chat's history lies in JSONL parts | |
| 0.2 | ChatWorker: CatchUp + Live with the 5 / 30 s buffer, reconcile, graceful shutdown | A new message reaches a file within 30 s | |
| 0.3 | Recover, FolderWatcher, refetch, `_status.json` | Deleted folder → refetched; killed process → no gaps or duplicates | |
| 0.4 | Trim (CLI), DiskGuard, `_trim_log.jsonl`, command queue | Fake-disk test passes; `trim 50` works against a running service | |
| 0.5 | Tray, notifications, autostart, `set-root` | Runs after a reboot without a console; the folder moves from the tray | |
| 0.6 | Edit and delete events, daily recheck, hot library reload | An edit made while the laptop was off appears after recheck; a new library entry is picked up without restart | |
| 0.7 | Media: voice, round videos, photos | Files beside the JSONL, trimmed with their part | |
| 1.0 | Integration with ChatRadar (variant A or B) | ChatRadar reads ChatImport data | |

## 2. Stages

### Stage 0.0 — Repository

**Status.** Done 2026-10-29: branch `chatimport` cut from `main`; ChatRadar code, tests,
migrations, Docker and panel removed; uv project `chatimport` on Python 3.14 with Telethon,
platformdirs, filelock and Typer; `chatimport --version`; config and library templates;
rules, agents, skills, CI and docs rewritten for ChatImport.

### Stage 0.1 — One chat's history on disk

Goal: the history of one library chat lies in `ChatImport` in the record format, split into
parts. No live mode, tray or trimming yet. Order of work:

| # | Module | What | Done when |
|---|---|---|---|
| 1 | `paths.py` | app folders via `platformdirs`; data root by priority (§7.3), no `set-root` yet | test: flag > env > config > Desktop |
| 2 | `config.py` | `tomllib` → dataclasses with the defaults of `config.example.toml`; clear validation errors | an empty config gives every default |
| 3 | `library.py` | read `chats.toml`, no watching yet | broken TOML → a clear error |
| 4 | `cli.py` + `telegram/client.py` | `chatimport login`, `chatimport dialogs` | the owner sees their groups and channels with `chat_id` |
| 5 | `telegram/resolve.py` | every ref kind → `chat_id`; people and bots rejected | `chatimport chats list` shows statuses |
| 6 | `telegram/mapper.py` | `Message → dict` with sender names | table-driven tests on fake messages |
| 7 | `storage/layout.py`, `writer.py`, `state.py` | part names, append with threshold, atomic writes, `state.json` | part-splitting tests with a 1 KB threshold |
| 8 | `worker.py` (part) | HeadBackfill + TailBackfill newest to oldest for one chat, with pauses and FloodWait | `chatimport run --once --chat <name>` fetches the chat and exits |
| 9 | Manual check (owner) | one small chat, then the largest | files open, `msg_id` ascends, a rerun adds no duplicates |

Acceptance: `just check` green; a second `run --once` appends nothing (dedup by `last_id`);
Ctrl+C mid-backfill and a rerun continue where it stopped without duplicates; the session
and real configs never reach git.

### Stages 0.2–1.0

Scope per the overview table and `docs/architecture.md`; each gets its detailed plan when it
becomes next.
