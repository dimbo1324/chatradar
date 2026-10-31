# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

Not yet run against a real Telegram account; everything below is verified with a scripted
fake of Telegram (3155 tests, 100 % line and branch coverage).

### Added

- Branch `chatimport`: the ChatImport project (uv, Python 3.14, Telethon, platformdirs,
  filelock, Typer, pystray, Pillow), `config.example.toml`, `chats.example.toml`, design and
  roadmap in `docs/`.
- Account and library: `login`, `dialogs`, `chats list|add|disable|enable`; refs as links,
  `@username`, numeric ids or exact titles; invite links never make the account join.
- Collection: full history backfill newest to oldest, catch-up, live batches (5 messages or
  30 s), reconcile every 10 minutes, `edit` and `delete` records, daily recheck of the last
  7 days, hot reload of `chats.toml`, optional media download (`media.enabled`).
- Storage: `ChatImport/<slug>_<chat_id>/YYYY-MM_NNN.jsonl` parts of 20 MB, `state.json`,
  recovery after a crash, refetch of a deleted chat folder, `_status.json`,
  `_trim_log.jsonl`.
- Commands: `run [--once] [--chat]`, `tray`, `status`, `pause`/`resume`, `recheck`,
  `trim 25|50|75`, `backfill --deeper`, `check [--repair]`, `export-json`,
  `set-root [--move]`; a running service takes them through the control folder.
- Disk guard: below 15 GB free the oldest parts are deleted until 17 GB are free, keeping
  the last 30 days.
- A rotating log file `%LOCALAPPDATA%\ChatImport\logs\chatimport.log`.
- `export-json --names/--no-names`.
- Application icon (`src/chatimport/assets/icon.png` and `icon.ico`): the tray shows it with a
  green, grey or red badge for running, paused or failed.
- Application icon (`src/chatimport/assets/icon.png`, `icon.ico`): the tray shows it with a
  green, grey or red badge for running, paused or failed.

### Changed

- `export-json` writes to `<data root>/_exports/<chat folder>.json` by default and leaves
  sender names and the raw Telegram object out unless `--names`.
- Chat folder names transliterate Cyrillic and drop accents instead of falling back to
  `chat_<id>`; existing folders are found by `state.json`, never renamed.
- Titles, names and `--chat` selectors match regardless of letter case and Unicode
  composition; `telegram.me` links and query strings name the same chat as `t.me`.
- Below the low watermark history downloads stop for good (`floor_reason = "disk"`) instead
  of pausing; `backfill --deeper` continues them.
- History is downloaded one chat at a time (`backfill.max_parallel_chats`).
- `run`, `status` and the tray warn when the data folder is under OneDrive.
- CLI tables align titles with emoji and wide letters; an explicit `PYTHONIOENCODING` is
  respected.

### Fixed

- A control command (for example `trim`) could run twice; it now runs at most once, and the
  CLI waits longer for long commands.
- A crash while rewriting a month of several parts could lose records.
- A refetch over an existing folder replaced the current month and lost its edits,
  deletions and media records.
- A `state.json` that could not be read for a moment was treated as missing and rebuilt,
  losing backfill progress.
- A live message arriving after a newer one was dropped; it is now merged in order.
- One failing history download stopped live collection of that chat.
- A pause was lost on restart; a chat without access was never retried.
- The folder watcher acted on a folder Explorer was still deleting.
- Windows: a reader holding a file (antivirus, indexer) made writes and trims fail.
- The recheck time drifted by an hour after a DST change.
- `run --once` stopped at the first failing chat.
- Status showed stale counts after a trim or recover; the tray tooltip failed on emoji.

### Security

- `state.json` part names are validated, so a damaged state cannot make a trim delete files
  outside the chat folder.
- Malformed or oversized control files are rejected without stopping the control server.
- Downloaded media with a risky extension get `.bin` appended; on Windows every media file
  is marked as downloaded from the internet.
- With `include_sender_names = false`, names and phone numbers are also removed from `raw`.
- Invite links are masked in `_status.json`, notifications, errors and logs.
- `set-root` refuses the application folder (it holds the session) and an unrelated
  non-empty folder; a cross-volume move does not follow links or junctions.
- On Linux and macOS the session, config and application folders are owner-only.
- `_unrouted_deletes.jsonl` is capped at 2 MiB.
- The tray's "Open log" opens only log files.

### Removed

- ChatRadar code, tests, migrations, Docker image and web panel on this branch; they stay
  on `main`.
