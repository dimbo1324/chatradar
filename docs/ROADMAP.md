# ChatImport — Roadmap

The plan and the progress record. Stages run in order; **the first stage without a
`**Status.**` line is next**. Skipping ahead needs an owner decision in `docs/decisions.md`.
Design details for every stage: `docs/architecture.md`.

## 1. Overview

| Stage | What | Done when | Status |
|---|---|---|---|
| 0.0 | Repository prepared on branch `chatimport`: stack, tooling, rules, docs | `just check` green on an empty package | done 2026-10-29 |
| 0.1 | Config, `chats.toml` library, `login`, `dialogs`, mapper with sender names, chunked writer, full backfill of one chat | One chat's history lies in JSONL parts | implemented 2026-10-29; live login not yet run |
| 0.2 | ChatWorker: CatchUp + Live with the 5 / 30 s buffer, reconcile, graceful shutdown | A new message reaches a file within 30 s | implemented 2026-10-29 |
| 0.3 | Recover, FolderWatcher, refetch, `_status.json` | Deleted folder → refetched; killed process → no gaps or duplicates | implemented 2026-10-29 |
| 0.4 | Trim (CLI), DiskGuard, `_trim_log.jsonl`, command queue | Fake-disk test passes; `trim 50` works against a running service | implemented 2026-10-29 |
| 0.5 | Tray, notifications, autostart, `set-root` | Runs after a reboot without a console; the folder moves from the tray | implemented 2026-10-29; tray not run on a real display |
| 0.6 | Edit and delete events, daily recheck, hot library reload | An edit made while the laptop was off appears after recheck; a new library entry is picked up without restart | implemented 2026-10-29 |
| 0.7 | Media: voice, round videos, photos | Files beside the JSONL, trimmed with their part | implemented 2026-10-29; no real download yet |
| 1.0 | Integration with ChatRadar (variant A or B) | ChatRadar reads ChatImport data | |

## 2. Stages

### Stage 0.0 — Repository

**Status.** Done 2026-10-29: branch `chatimport` cut from `main`; ChatRadar code, tests,
migrations, Docker and panel removed; uv project `chatimport` on Python 3.14 with Telethon,
platformdirs, filelock and Typer; `chatimport --version`; config and library templates;
rules, agents, skills, CI and docs rewritten for ChatImport.

### Stage 0.1 — One chat's history on disk

**Status.** Implemented 2026-10-29T20:25-03:00 (commits `72c8ea6`, `0897b76`): `paths`,
`config`, `library`, `login`, `dialogs`, `chats list|add|disable|enable`, `telegram/resolve`,
`telegram/mapper` with sender names, the chunked writer with `state.json`, head and tail
backfill with pauses and FloodWait, `run --once [--chat]`. Verified only against the
scripted gateway in `tests/fakes.py`. **Not verified:** row 9 below, the manual check with a
real account (`chatimport login`, one small chat, then the largest), is still the owner's
next step (spec §19.2 step 9); nothing has talked to Telegram yet.

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

### Stages 0.2–0.7

**Status.** Implemented 2026-10-29T20:25-03:00 together with 0.1, covered by tests at
2026-10-29T22:43-03:00 (`69cd4ac`: 2662 tests, 99 % line and branch coverage):

- **0.2** `ChatWorker`: catch-up, live buffer (5 messages / 30 s), reconcile every
  10 minutes, flush on shutdown.
- **0.3** recover on start, `FolderWatcher` (refetch after two confirming checks),
  `_status.json`, `status`, `check [--repair]`.
- **0.4** `trim 25|50|75`, `DiskGuard` (15 / 17 GB, `protect_recent_days`),
  `_trim_log.jsonl`, the control-folder command queue, `pause`/`resume`.
- **0.5** tray (pystray) with notifications and dialogs, `set-root [--move]`. The autostart
  is documented (`docs/architecture.md` §14), not scripted.
- **0.6** `edit`/`delete` records, daily recheck, `recheck`, hot library reload,
  `backfill --deeper`, `export-json`.
- **0.7** `MediaDownloader` for chosen types, `media_saved` records, media trimmed with
  their messages, downloads paused by the disk gate.

**Not verified** outside tests: any real Telegram traffic (login, FloodWait, events, media
downloads), the tray on a real display, autostart after a reboot, `set-root --move` across
two real volumes, the disk guard on a really full disk. The owner's manual check (stage 0.1
row 9, then the stage "done when" columns above) comes first.

### Hardening and refactor pass

**Status.** Done 2026-10-30T12:15:42-03:00 (`005b452` … `c6f3f6c`): five audits (security,
correctness, i18n, performance, architecture) and their fixes. Highlights: control commands
run at most once; one backfill at a time (`BackfillSlots`); crash-safe multi-part month
rewrite (`storage/month_commit.py`); `StateUnreadable` instead of overwriting a state that
cannot be read now; disk-guard stop persisted with `floor_reason = "disk"`; late live
messages merged; bounded live queue; Cyrillic folder slugs; NFC/casefold text matching;
export without names into `_exports/`; media extension allowlist and Mark-of-the-Web;
rotating log file; modules split under 500 lines. Re-measured 2026-10-31 on Windows:
3155 tests passed, 3 skipped (POSIX-only), 100 % line and branch coverage. Deferred findings:
`docs/backlog.md`.

### Stage 1.0 — Integration with ChatRadar

Open: variant A or B (`docs/architecture.md` §15) is an open owner question
(`docs/decisions.md`). It starts after the owner's live check of 0.1–0.7.
