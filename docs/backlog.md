# Backlog

Work consciously deferred, with the reason, to come back to. Shipped items move to
`CHANGELOG.md`. Finding ids (C, P, A) refer to the audits of 2026-10-30.

## Verification

- **The owner's live check** (`docs/ROADMAP.md`, stage 0.1 row 9): `login`, one small chat,
  then all of them; then the tray on the real desktop, autostart after a reboot,
  `set-root --move` across two real volumes, media downloads. Nothing has talked to Telegram
  yet; only the scripted fake has.

## Deferred findings

- **C5 (rest).** A corrupt `state.json` is rebuilt from the parts, but the rebuilt state
  gets no `floor_reason = "rebuilt"` and no notification. Deferred: a new `floor_reason`
  value touches the state format and status consumers; the rebuild is logged.
- **P7(b).** Trimming still decodes a removed part to find its media ids (only when that
  month has a media folder). Deleting media by the part's id range is unsafe: parts of one
  month can overlap in `msg_id` after merges.
- **P8.** The disk guard rereads each chat's oldest part on every deletion step; no cache
  across iterations. Cheap at the expected volume (§5.3).
- **P10.** The newest month (head backfill) is still collected whole in memory before it is
  written. Fine for ~450 messages a month; a very busy chat would want streaming.
- **P12 (rest).** `_unrouted_deletes.jsonl` is capped and written in a thread, but every
  event still makes its own write; batching was not done.
- **C7 (rest).** Reconcile catches up from `last_id` only (`iter_since(last_id)`); it does
  not overlap below it (`last_id - N`). Late messages that arrive as events are merged; ones
  that never arrive wait for the daily recheck.
- **C1 (rest).** `backfill.pause_between_chats_sec` is not applied after a backfill slot is
  released; it only staggers the first launch of fresh workers and the chats of `run --once`.
- **A12.** The public `ChatWorker.folder` still resolves the folder by scanning the root
  (`find_chat_folder`) on every call.
- **`deeper` without `ChatStore`.** The `deeper` command and the offline `backfill --deeper`
  still go through `offline.lower_floor_state` instead of `storage/chat_store.ChatStore`.
- **Logging in the app.** `ChatImportApp` does not configure logging itself; the entry
  points (`run`, `tray`) do. Embedding the app elsewhere needs its own
  `configure_logging` call.
- **`backfill.use_takeout`** is read from the config but not used (no takeout session).

## Repository

- Dependabot does not watch branch `chatimport` (it reads only the default branch); update
  dependencies by hand with `uv lock --upgrade-package <name>` until the branches merge.
- `.claude/settings.json` still allows ChatRadar-only commands (`chatradar --help`, Docker
  Compose reads). Harmless; tidy up with the owner's approval.
- `AGENTS.md` is at 29.7 of its 30 KiB budget: the next rule addition needs a module to be
  tightened or moved to the extended tier (owner approval when content leaves the file).
