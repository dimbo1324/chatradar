# ChatImport — Architecture

English version of the owner's spec v1.2 (2026-10-29; the Russian original is kept outside
the repository). This file is the reference inside the repository; where code and this file
disagree, the code is the fact and this file is fixed in the same task.

## 1. Goals and non-goals

ChatImport keeps the full text history of about eight Telegram groups and channels locally,
in a machine-readable form. It reacts to new messages almost at once but writes in batches;
it is controlled by simple actions (delete a folder to refetch it, `trim` to drop old
history); it guards free disk space; and its record format already has room for media.

It does **not**: read Telegram Desktop's encrypted `tdata` (it is its own client; Telegram
Desktop may be closed); analyse messages (that is ChatRadar's job); fetch secret chats
(unavailable through the API); send or publish anything anywhere.

## 2. Requirements

| ID | Requirement |
|---|---|
| F1 | First run for a chat fetches its whole available text history. |
| F2 | Then new messages are written in batches of N (default 5) or every T seconds (default 30), whichever comes first. |
| F3 | Format: JSONL, one JSON object per line. |
| F4 | Output folder `ChatImport` on the current user's Desktop by default; the path changes without code edits (command, tray, environment variable, config), moving existing data (§7.3). |
| F5 | A deleted chat folder means a full refetch of that chat; a deleted root means all chats. |
| F6 | Disk guard: when the volume has less than 15 GB free, delete the oldest messages until at least 17 GB is free; recent messages stay. |
| F7 | Manual trim of the oldest 25 / 50 / 75 % — strictly in order, for all chats or one. |
| F8 | Edits and deletions are separate records; history is never rewritten. |
| F9 | Every record has a `media` field; enabling media is a setting, not a redesign. |
| F10 | **Only** groups and channels from the `chats.toml` library are tracked; private dialogs and everything else are ignored. The library changes without a restart (§7.2). |
| F11 | Sender names (`sender_name`, `sender_username`) are stored, not only `sender_id`. |
| F12 | Daily recheck of the last N days (default 7) records edits and deletions missed while the service was off (§8.7). |

| ID | Non-functional |
|---|---|
| N1 | Python ≥ 3.14. |
| N2 | Free open-source dependencies only. |
| N3 | No duplicates and no losses across restart, crash or power loss (at-least-once intake + dedup by `msg_id`). |
| N4 | Files are not held open between writes, so Windows can delete a folder. |
| N5 | Gentle on Telegram limits: pauses, FloodWait handling, no aggressive parallelism. |
| N6 | One failing subtask never brings the service down; status is visible in `_status.json` and the tray. |
| N7 | One service instance per user. |

## 3. Stack

| Need | Component | License |
|---|---|---|
| Language | Python 3.14 | PSF |
| Project manager | uv | MIT / Apache-2.0 |
| Telegram (MTProto) | Telethon 1.x | MIT |
| Faster crypto (optional) | cryptg, only if a 3.14 wheel exists | CC0 |
| Desktop and app folders | platformdirs (`user_desktop_dir`, `user_data_dir`) | MIT |
| Single instance | filelock | Unlicense |
| CLI | Typer (with Click and Rich) | MIT / BSD-3 |
| Tray (optional) | pystray + Pillow | LGPL-3.0 / MIT-CMU |
| Confirmation dialogs | tkinter | PSF (stdlib) |
| Config | `tomllib` (read-only) | stdlib |
| Free space | `shutil.disk_usage` | stdlib |
| Logs | `logging` + `RotatingFileHandler` | stdlib |
| Development | pytest, pytest-asyncio, ruff, pyright | MIT |

Deliberately **not** used: a database (the files are the storage), watchdog/inotify (polling
every 10 s is more reliable across systems and Explorer deletions), Docker (the service needs
the user's Desktop and tray).

## 4. Components

```mermaid
flowchart LR
  TG[(Telegram)] <--> CL[Telegram client<br/>Telethon]
  CL -- NewMessage / Edited / Deleted --> RT[Router]
  RT --> W1[ChatWorker: chat 1]
  RT --> Wn[ChatWorker: chat N]
  W1 & Wn -- history / catch-up --> CL
  W1 & Wn --> ST[Storage<br/>JSONL + state.json]
  FW[FolderWatcher] -- folder missing --> W1 & Wn
  DG[DiskGuard] -- free space low --> TR[Trimmer]
  CTL[Control<br/>CLI / tray] -- trim, pause, status --> TR
  TR --> ST
  SUP[Supervisor] -. restarts failed tasks .-> W1 & FW & DG
  ST --> FS[(ChatImport folder)]
```

| Component | Does | Does not |
|---|---|---|
| TelegramClient | connection, session, `iter_messages`, events, FloodWait | write files |
| Mapper | pure `Telethon Message → dict` (§6) | any I/O |
| Library | reads `chats.toml`, resolves refs to `chat_id`, watches the file | fetch messages |
| Router | routes events to workers by `chat_id`; drops anything outside the library | write files |
| Rechecker | daily comparison of the last N days with Telegram | write directly — hands records to the worker |
| ChatWorker (one per chat) | state machine: backfill, catch-up, live buffer, writes | touch other chats |
| Storage | layout, atomic writes, `state.json`, recovery | know about Telegram |
| Trimmer | deletes old messages in order (manual and automatic) | decide *when* |
| DiskGuard | checks free space every 5 min, calls the trimmer | |
| FolderWatcher | checks folders every 10 s, notifies workers | |
| Control | commands from CLI/tray, `_status.json` | |
| Supervisor | starts tasks, restarts failed ones with exponential backoff | |

**One writer.** Only the service process writes into `ChatImport`, and inside it only the
chat's worker (or the trimmer holding that chat's `asyncio.Lock`). CLI and tray send
commands (§9.3). No inter-process locking of data files is needed.

### Worker state machine

```mermaid
stateDiagram-v2
  [*] --> Recover: start / folder found
  [*] --> HeadBackfill: no folder
  Recover --> CatchUp
  HeadBackfill --> CatchUp: current month written
  CatchUp --> Live: reached last_id
  Live --> Live: batch of 5 / 30 s
  Live --> CatchUp: reconcile every 10 min
  Live --> HeadBackfill: folder deleted
  state Live {
    [*] --> TailBackfill: history incomplete
    TailBackfill --> [*]: reached chat start / floor
  }
  Live --> Paused: pause
  Paused --> CatchUp: resume
```

- **HeadBackfill** — the current month (newest messages).
- **CatchUp** — `iter_messages(min_id=last_id)`: everything since the service last listened.
- **Live** — events into a buffer, written in batches.
- **TailBackfill** — older months in the background, in parallel with Live (other files).

## 5. Storage on disk

### 5.1 Locations (Windows; `platformdirs` gives the equivalents elsewhere)

| What | Where | Why |
|---|---|---|
| Chat data | `%USERPROFILE%\Desktop\ChatImport\` | default; changeable (§7.3) |
| Config | `%LOCALAPPDATA%\ChatImport\config.toml` | deleting data must not delete settings |
| Library | `%LOCALAPPDATA%\ChatImport\chats.toml` | a separate hand-edited file |
| Session | `%LOCALAPPDATA%\ChatImport\session\chatimport.session` | a secret; survives data deletion |
| Logs | `%LOCALAPPDATA%\ChatImport\logs\` | |
| Instance lock | `%LOCALAPPDATA%\ChatImport\chatimport.lock` | |
| Command queue | `%LOCALAPPDATA%\ChatImport\control\` | |

### 5.2 Layout

```
ChatImport/
├── _status.json               # service status, refreshed every minute (read-only)
├── _trim_log.jsonl            # every deletion: when, what, why
└── <slug>_<chat_id>/          # for example example_group_-1001234567890
    ├── state.json             # chat state (§6.3)
    ├── 2024-03_001.jsonl      # <UTC month>_<part>; lines ascend by msg_id
    ├── 2026-09_001.jsonl
    ├── 2026-09_002.jsonl      # the month did not fit into one part
    └── 2026-10_001.jsonl      # current part of the current month — live appends here
```

- A chat is identified by `chat_id` in `state.json`, never by its folder name: renaming the
  chat in Telegram or the folder by hand changes nothing.
- Names starting with `_` are service files, not chats.
- **Month files are split into parts.** The part is the unit of storage, deletion and
  accounting in `state.json`.

| Rule | Description |
|---|---|
| Name | `YYYY-MM_NNN.jsonl`: UTC month and zero-padded part number (`001`–`999`); name order is chronological |
| Threshold | `max_chunk_mb = 20`. Before appending a batch: if the current part is ≥ 20 MB, open the next. A batch is never split, so a part may slightly exceed the threshold |
| Order | Part `_001` holds a month's oldest messages; inside a part, ascending `msg_id` |
| Backfill | A month is collected in memory, sorted and written straight into parts by threshold, each part atomically |
| Edits and deletions | Appended to the last part of the event's month |
| Threshold change | Applies to new parts only; old parts are not re-split |
| Accounting | Each part is an entry in `state.json → chunks` (records, first and last `msg_id`, bytes) |
| Trimming | Auto-trim deletes the oldest whole part; manual trim deletes whole parts and cuts one boundary part (§8.5, §8.6) |

### 5.3 Expected volume

One record with sender names is about 0.4–0.6 KB. Earlier profiling of the owner's chats
(8 chats, ~177 thousand messages over 2022–2026): ~450 messages per chat per month,
~0.2–0.3 MB per month file, ~100 MB for the whole text archive (~400 MB with `include_raw`).
Text alone will not fill a disk; the 15 GB guard matters once media is on (§12). Parts keep
manual trims fast, auto-trim fine-grained and files easy to open; most months will be a
single `_001`.

### 5.4 Why JSONL

Appending 5 messages adds 5 lines instead of rewriting a file; old history is deleted as
whole files; a crash damages at most the last line, which recovery cuts; reading is a
streaming `for line in f: json.loads(line)`. `chatimport export-json --chat X` assembles a
classic JSON array when needed.

## 6. Data format

### 6.1 Message record (`kind = "message"`)

```json
{
  "v": 1,
  "kind": "message",
  "source": "telegram",
  "chat_id": -1001234567890,
  "msg_id": 4512,
  "date": "2026-10-29T21:03:11Z",
  "edit_date": null,
  "fetched_at": "2026-10-29T21:03:40Z",
  "sender_id": 777000111,
  "sender_name": "Example Person",
  "sender_username": "example_user",
  "text": "Where can I get an apostille in Montevideo?",
  "reply_to_msg_id": 4507,
  "topic_id": null,
  "grouped_id": null,
  "forwarded": false,
  "service": null,
  "link": "https://t.me/c/1234567890/4512",
  "media": null
}
```

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Schema version. New fields keep it; removal or a change of meaning bumps it |
| `kind` | str | `message` · `edit` · `delete` |
| `chat_id`, `msg_id` | int | Message key; `msg_id` is unique within a chat |
| `date`, `edit_date`, `fetched_at` | ISO 8601 UTC | Always UTC with a `Z` suffix |
| `sender_id` | int \| null | `null` for anonymous admins and channels |
| `sender_name` | str \| null | Display name at fetch time (first + last name, or channel title); on by default (`include_sender_names`) |
| `sender_username` | str \| null | The sender's @username, if any |
| `text` | str | As is; empty string for media-only messages |
| `reply_to_msg_id`, `topic_id` | int \| null | Reply and forum topic (in forums `reply_to` may point at the topic) |
| `grouped_id` | int \| null | Album |
| `forwarded` | bool | Forwarded message |
| `service` | str \| null | Service event type (`join`, `leave`, `pin`, …) |
| `link` | str \| null | `t.me/<username>/<id>` or `t.me/c/<id without -100>/<id>` |
| `media` | object \| null | Attachment description (§12); `file = null` while media is off |

`include_raw = true` adds `raw` with the full `message.to_dict()` (dates as ISO, bytes as
base64) — compatible with ChatRadar's raw payload. Off by default: 3–5× the volume.

### 6.2 Edit and delete

```json
{"v":1,"kind":"edit","chat_id":-1001234567890,"msg_id":4512,"edit_date":"2026-10-29T21:10:02Z","text":"new text","media":null,"detected_by":"event","fetched_at":"2026-10-29T21:10:05Z"}
{"v":1,"kind":"delete","chat_id":-1001234567890,"msg_ids":[4510,4511],"detected_by":"event","fetched_at":"2026-10-29T21:11:00Z"}
```

- `detected_by`: `event` (real time) or `recheck` (§8.7).
- Written into the file of the **event's** month; history stays append-only.
- Consumers apply them on top: the latest `edit` wins; `delete` is a mark. An edit of a
  message whose month was trimmed is ignored.
- For **basic small groups** Telegram sends deletions without a `chat_id`; those go to
  `ChatImport/_unrouted_deletes.jsonl`. Supergroups and channels always carry it.

### 6.3 `state.json`

```json
{
  "v": 1,
  "chat_id": -1001234567890,
  "title": "Example group",
  "username": "example_group",
  "phase": "live",
  "last_id": 4512,
  "floor_id": 118,
  "floor_reason": "manual_trim_25",
  "last_recheck_at": "2026-10-29T07:00:00Z",
  "backfill": {"done": false, "head_id": 4380, "oldest_done_id": 2201, "started_at": "2026-10-29T20:00:00Z"},
  "chunks": {
    "2026-09_001": {"records": 1830, "first_id": 2201, "last_id": 3999, "bytes": 912345},
    "2026-10_001": {"records": 520, "first_id": 4000, "last_id": 4512, "bytes": 260111}
  },
  "updated_at": "2026-10-29T21:03:40Z"
}
```

- `last_id` — the highest written `msg_id`; anything `≤ last_id` is never written again.
- `floor_id` — the history floor: the service never fetches older messages by itself.
  Trims and a disk-space stop raise it; only `backfill --deeper` or deleting the chat
  folder lowers it.
- **`state.json` is a cache.** The JSONL files are the truth; a missing or broken state is
  rebuilt by scanning them (§10.2). Writes are atomic (temp file → `os.replace`).

## 7. Configuration

### 7.1 `config.toml`

Template with every default: `config.example.toml` in the repository root. Sections:
`telegram` (API id and hash, `flood_sleep_threshold`), `output` (`root_dir`,
`include_sender_names`, `include_raw`, `max_chunk_mb`), `library` (`file`,
`reload_check_seconds`), `recheck` (`enabled`, `days`, `daily_at`, pause), `live`
(`flush_every_messages`, `flush_every_seconds`, `reconcile_every_minutes`), `backfill`
(`batch_size`, pauses, `max_parallel_chats = 1`, `use_takeout`), `disk` (watermarks 15/17 GB,
`check_every_minutes`, `protect_recent_days = 30`), `watch` (`check_every_seconds`,
`confirm_checks = 2`), `media`, `events`. An empty file gives all defaults. Changes apply
on restart (or "Reload config" in the tray), except the library and the output path, which
change live.

### 7.2 Library `chats.toml`

The only source of truth for what is tracked. Template: `chats.example.toml`. Each
`[[chat]]` has `ref`, optional `name` (folder name) and optional `enabled`.

| `ref` kind | Resolved by | Notes |
|---|---|---|
| `https://t.me/name`, `@name` | `get_entity` | public groups and channels |
| `https://t.me/+…`, `t.me/joinchat/…` | invite check | **never joins by itself**: not a member → status "need to join" |
| `-100…` | among your dialogs | the most reliable |
| text | exact title among your dialogs | two equal titles → "ambiguous, use a link"; a rename breaks it |

- After the first resolution the `chat_id` is kept in `state.json`; later renames do not
  matter.
- A ref that points at a person or a bot gets "not a group or channel" and is ignored.
- The file is checked every 10 s by mtime: a new entry starts a backfill; `enabled = false`
  or removal stops collection and keeps the folder.
- A syntax error keeps the previous valid version running and shows the error in the tray
  and `_status.json`.
- Each entry's resolution (found / need to join / not found / ambiguous) shows in
  `chatimport chats list` and `_status.json`.

### 7.3 Output path

First match wins: `--root <path>` → `CHATIMPORT_ROOT` → `output.root_dir` →
`<Desktop>\ChatImport`. `~` and environment variables expand; if the path does not end in
`ChatImport`, the folder is created inside it.

`chatimport set-root <path> [--move]` (or tray "Change folder…"): validate the path
(creatable, writable, not inside the old folder; warn about OneDrive) → flush buffers and
pause workers → with `--move` move the data (rename on the same volume, verified copy and
delete across volumes; without it, a full refetch with a warning) → save the path to
`config.toml` and resume → DiskGuard watches the new volume.

## 8. Scenarios

### 8.1 Start

1. Take the single-instance lock; if taken, say "already running" and exit.
2. Read the config and connect (the session exists after `chatimport login`).
3. Read the library and resolve refs; unresolved ones go to the log, status and a
   notification.
4. Subscribe to events **before** starting workers (events queue up; nothing is lost).
5. Per chat: folder found by `state.json` → Recover → CatchUp → Live; no folder →
   HeadBackfill.
6. Start FolderWatcher, DiskGuard, Control and the `_status.json` refresh.

### 8.2 Full backfill (newest to oldest)

So that any stop leaves the most recent history already on disk:

1. **HeadBackfill.** `head_id` = newest message; fetch the current month, sort, write
   atomically; `last_id = head_id`; go to CatchUp → Live within minutes.
2. **TailBackfill** (background, one chat at a time): `iter_messages(offset_id=oldest_done_id)`
   walks back; when a message of the previous month appears, the collected month is sorted
   and written in parts, each atomically; `oldest_done_id` and `chunks` update.
3. Chat start or `floor_id` reached → `backfill.done = true`.
4. Interrupted → resume from `oldest_done_id`; an unfinished month is refetched
   (idempotent).
5. Free space below `low_watermark` → stop, `floor_id = oldest_done_id`,
   `floor_reason = "disk"`, notify. No automatic resume (it would fetch and delete forever).

Pause `pause_between_chats_sec` between chats; a FloodWait above the threshold sleeps only
that worker while the other chats stay live.

### 8.3 Live

1. `NewMessage` → Router → the chat's worker queue.
2. The worker buffers; flush at `flush_every_messages` records **or** `flush_every_seconds`
   after the first buffered record, whichever comes first.
3. Flush: drop `msg_id ≤ last_id` → sort by `msg_id` → open the current part for append (or
   the next if ≥ `max_chunk_mb`) → write → `flush` + `fsync` → **close** → update
   `state.json` (`last_id`, `chunks`).
4. A batch crossing a month boundary is split into its months' files.
5. `MessageEdited` / `MessageDeleted` go through the same buffer as `edit` / `delete`.
6. Every `reconcile_every_minutes` a safety CatchUp picks up what events missed
   (disconnects, sleep, known update gaps).
7. On shutdown (Ctrl+C, tray exit) the buffer is flushed.

### 8.4 Folder deletion

| Deleted | Reaction |
|---|---|
| A chat folder | after 2 checks in a row (~20 s): HeadBackfill from scratch, `floor_id` reset |
| The whole `ChatImport` | recreate; HeadBackfill for every chat, one at a time |
| Only `state.json` | rebuild from files, **no** refetch |
| Some part files | treated as a manual trim: `floor_id` rises to the first remaining message |
| The current month's file | likewise; new messages go into a new file |

Two checks are needed because Explorer deletes a large folder gradually. Files are closed
between writes, so Windows does not block the deletion.

### 8.5 Automatic disk guard

```
every 5 minutes:
  free = disk_usage(root_dir).free
  if free < 15 GB:
      pause TailBackfill in every chat
      while free < 17 GB:
          candidate = the oldest part across ALL chats that is entirely older than protect_recent_days
          if none: notify "space is low, but everything allowed is already deleted" -> stop
          os.remove(candidate)            # not the Recycle Bin, or no space is freed
          raise that chat's floor_id, update chunks, append to _trim_log.jsonl
          free = disk_usage(root_dir).free
      notify "freed X GB: deleted parts ..."
```

Oldest first across all chats; the 15/17 GB gap prevents trimming on every message;
`protect_recent_days` keeps recent history even when something else filled the disk.

### 8.6 Manual trim 25 / 50 / 75 %

`chatimport trim 50` (all chats) or `chatimport trim 50 --chat example_group`:

1. Per chat: `total = sum(chunks[*].records)`, `target = floor(total × p)`.
2. Delete parts from the oldest while their records sum to ≤ `target`.
3. The remainder in the boundary part: read it, skip the first `k` lines, write the rest to
   a temp file → `os.replace`.
4. `floor_id` = first remaining `msg_id`; update `chunks`; append to `_trim_log.jsonl`.
5. Percentages are **per chat** — half of each chat's history, not half of the bytes.

Allowed values: 25, 50, 75 (100 % = delete the folder). The tray asks for confirmation; the
CLI asks `y/N` (`--yes` for scripts).

### 8.7 Daily recheck of the last 7 days

Edit and delete events arrive only while connected; the recheck catches what changed while
the laptop was off.

**When:** daily at `recheck.daily_at` and on start if `last_recheck_at` is over 24 h old.
One chat at a time with pauses; a chat in backfill is postponed.

**How (one chat):**

1. Window: now minus 7 days up to `last_id`, never below `floor_id`.
2. Read the window's current state from the files (latest version of each `msg_id` after
   existing `edit`/`delete` records).
3. Fetch the window from Telegram: `iter_messages(offset_date=…, reverse=True)` up to
   `last_id`.
4. Compare: newer `edit_date` or different text/media → `edit` with `detected_by:
   "recheck"`; in the file but not returned → `delete` with `detected_by: "recheck"`; returned
   but not in the file → append as a normal `message` (consumers sort by `msg_id`).
5. Update `last_recheck_at`.

This also places small-group deletions that arrived without a `chat_id`. Load: a few
thousand messages and tens of requests a day.

### 8.8 Library changes at run time

| Change in `chats.toml` | Reaction |
|---|---|
| Entry added | resolve → create folder → HeadBackfill (in the shared backfill queue) |
| `enabled = false` / entry removed | flush, stop the worker, unsubscribe; data stays |
| Re-enabled | Recover → CatchUp from `last_id` |
| `name` changed | the folder is not renamed; the name applies to new folders |
| Syntax error | keep the last valid version, show the error |

## 9. Control: CLI and tray

### 9.1 Commands

The full command list with the stage each arrives in is in
`.ai/project/14-command-reference.md`.

### 9.2 Tray menu

Status tooltip ("8 chats · live · 2.1 GB · 41 GB free"); open the ChatImport folder; change
folder…; open the library in the default editor; recheck now; trim → 25/50/75 % with
confirmation; pause / resume; reload config; open log; exit with a clean flush.
Notifications: low space, parts deleted, FloodWait over 10 minutes, login failure.

### 9.3 How CLI commands reach a running service

If the service runs, the CLI drops a command file into the control folder (for example
`trim-<uuid>.json` with `{"pct": 50, "chat": null}`); Control picks it up within ~1 s, runs it
and writes `…result.json`, which the CLI waits for. If the service is not running, the CLI
takes the single-instance lock and runs the command itself. No network ports.

### 9.4 `_status.json`

```json
{
  "updated_at": "2026-10-29T21:05:00Z",
  "service": "running",
  "disk": {"path": "C:\\", "free_gb": 41.2, "low_watermark_gb": 15},
  "total_bytes": 2254857830,
  "chats": [
    {"chat_id": -1001234567890, "title": "Example group", "phase": "live",
     "last_id": 4512, "backfill_done": false, "oldest_date": "2024-03-02T08:14:55Z", "records": 48210}
  ],
  "errors": []
}
```

## 10. Reliability and recovery

### 10.1 Guarantees

| Situation | Outcome |
|---|---|
| Clean shutdown | buffers flushed, nothing lost |
| Process killed / PC off | at most the buffer (≤ 5 messages / 30 s) is lost — CatchUp refetches it |
| Power loss mid-write | the last line may be cut — Recover trims it; the message is refetched |
| Sleep / no network | CatchUp on reconnect plus reconcile every 10 min |
| FloodWait | short: Telethon waits; long: that worker sleeps, others stay live |
| Session revoked | collection stops; notification "run `chatimport login`" |
| Removed from a chat | `phase = "no_access"`, data kept, notification |
| A subtask fails | Supervisor restarts it after 1 → 2 → 4 … 300 s; error in `_status.json` |

At-least-once intake + dedup by `msg_id` = no duplicates and no gaps.

### 10.2 Recover on start (per chat folder)

1. For each `*.jsonl`: if the last line does not parse, truncate to the last `\n`.
2. Missing or broken `state.json`: rebuild from files (`records`, `first_id`, `last_id`,
   `bytes`; `floor_id` = minimum `msg_id`; `backfill.done = false`).
3. `last_id = max(state.last_id, max msg_id in files)` — files win.
4. Parts deleted by hand: drop from `chunks`, raise `floor_id`.
5. Files missing from `chunks` (for example after a crash during a part switch): add them.

### 10.3 Atomic writes

- Live append: `open("a") → write → flush → os.fsync → close`, then `state.json` via
  `os.replace`. A crash in between leaves `state.json` behind; Recover step 3 fixes it.
- Backfilled parts and the trimmed boundary part: temp file in the same folder → `fsync` →
  `os.replace` (atomic within one volume on Windows).

## 11. Security and Telegram rules

- **A session is full account access.** It lives in the application data folder, never on
  the Desktop, in git or in cloud sync. It shows in Telegram → Settings → Devices, where it
  can be terminated.
- `api_id`/`api_hash` live only in the real config; the repository holds
  `config.example.toml`.
- **Sender names are personal data** (Uruguay, Ley 18.331): exports with names are for the
  owner's local work only; strip names before sharing or publishing.
- **OneDrive.** A synced Desktop uploads the archive and "Files On-Demand" distorts space
  accounting; set `output.root_dir` outside it.
- **Telegram terms.** Archiving chats you are a member of for yourself is close to normal
  client use, but since February 2026 the terms separately forbid scraping and using platform
  data for AI without participants' consent. Do not pass the export to third parties or to AI
  services for other people; settle this before building a product on it.
- **Limits.** Backfill one chat at a time with pauses; not on a fresh account; never shorten
  pauses for speed.

## 12. Media (later stage)

Every record already has `media`:

```json
"media": {"type": "voice", "mime": "audio/ogg", "size": 48213, "duration": 14,
          "width": null, "height": null, "file_name": null, "file": null}
```

Plan: `media.enabled = true` with chosen `types` and `max_file_mb`; a separate
MediaDownloader queue (one file at a time, own pauses) takes records with `file == null`,
refetches the message by `msg_id` right before downloading (file references expire), saves
to `media/<YYYY-MM>/<msg_id>[_<n>].<ext>` inside the chat folder and appends
`{"kind": "media_saved", "msg_id": …, "file": "media/2026-10/4512.ogg"}`. Trimming a part
deletes its media by the part's `first_id…last_id` range; the disk guard pauses media
downloads first. Voice transcription is a separate future consumer.

### Planned module layout

```
src/chatimport/
├── __main__.py
├── cli.py              # Typer: login, run, tray, status, trim, …
├── config.py           # TOML → dataclasses, validation
├── paths.py            # platformdirs: desktop, data, logs, control
├── app.py              # wiring, Supervisor, graceful shutdown
├── library.py          # chats.toml: read, watch, add/disable
├── telegram/
│   ├── client.py       # connection, history, events, FloodWait
│   ├── resolve.py      # library ref → chat_id
│   └── mapper.py       # Message → dict (pure)
├── recheck.py
├── storage/
│   ├── layout.py       # folders by chat_id, part names
│   ├── writer.py       # append, atomic part writes
│   ├── state.py        # state.json read/write/rebuild
│   └── recover.py      # cut broken lines, reconcile state with files
├── worker.py           # ChatWorker state machine, buffer
├── trim.py
├── guards/
│   ├── disk.py
│   └── folders.py
├── control.py          # control folder, _status.json
├── tray.py             # pystray, notifications, tkinter dialogs
└── media.py            # stage 0.7
tests/
├── fakes.py            # FakeTelegram: history and events from fixtures
└── test_mapper.py, test_writer.py, test_recover.py, test_trim.py, …
```

Dependencies are injected through constructors (Telegram client, `disk_usage`, clock), so
everything is testable without network and without a real 15 GB disk.

## 13. Testing

| What | How |
|---|---|
| Mapper | table-driven: fake Telethon objects → expected dict (text, reply, forum, forward, service, media) |
| Buffer and dedup | 5 messages → one write; 3 messages + 30 s (fake clock) → write; repeated `msg_id` dropped |
| Order | events out of order in a batch → ascending `msg_id` in the file |
| Parts | threshold 1 KB in tests: switch to `_002`; batches not split; backfill writes a month in several parts; `msg_id` order across parts |
| Recover | cut last line; deleted `state.json`; deleted part; part missing from `chunks` |
| Trim | 25/50/75 % on synthetic data; boundary part; `floor_id`; record counts |
| DiskGuard | fake `disk_usage`: deletes oldest first, stops at 17 GB, keeps `protect_recent_days` |
| FolderWatcher | deleted folder → refetch; deleted `state.json` only → no refetch |
| Library | every ref kind; ambiguous title; person rejected; hot add/disable; broken TOML does not stop the service |
| Recheck | edit, delete and gap inside the 7-day window found; nothing below `floor_id` touched; a rerun adds nothing |
| Path change | `set-root --move` on the same and another volume; without `--move` — warning and refetch; DiskGuard follows |
| Router | events from private dialogs or chats outside the library go nowhere |
| Windows | no open files after a flush; `os.replace` over an existing file |
| Integration | FakeTelegram with 3 chats: backfill → live → folder deleted → refetch → trim |
| Manual | live login, one small chat, then all eight — the owner's step |

## 14. Run and autostart

```bash
uv sync
uv run chatimport login          # once
uv run chatimport dialogs        # find your groups and channels
uv run chatimport chats add https://t.me/example_group
uv run chatimport tray           # normal operation
```

Windows autostart: Task Scheduler, trigger "at log on" with a 1-minute delay; action
`<project>\.venv\Scripts\pythonw.exe -m chatimport tray`; restart on failure every 5 minutes
up to 10 times; do not start a new instance if one runs. A single `.exe` through PyInstaller
may come later.

## 15. Integration with ChatRadar

- A `kind = "message"` record maps one to one onto ChatRadar's `RawRecord` (`source`,
  `chat_id`, `fetched_at`, `payload`); with `include_raw = true` the payload is the same
  `message.to_dict()` ChatRadar's Telethon connector stores.
- **Variant A (fast):** a `chatimport_dir` connector in ChatRadar reads the `ChatImport`
  folder incrementally (by `chunks` and `last_id`). The services stay independent.
- **Variant B (target):** move `telegram/`, `storage/writer.py` and `worker.py` into
  ChatRadar as `chatradar listen`, with the `ChatImport` folder as a `RawStore` variant.
- `mapper`, `worker` and `trim` carry no tray or CLI dependencies — that is what makes the
  move possible.
