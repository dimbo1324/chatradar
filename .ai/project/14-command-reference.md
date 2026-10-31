# Command Reference and Platform Notes

<!-- tier: extended -->

> **Essence.** Lookup material — every `chatimport` command (all implemented) and whether it needs the running service, where configuration, data and logs live, the control-queue protocol (claimed by rename, run at most once), CI jobs (pyright on Linux) and the Windows notes (UTF-8 consoles, `pythonw` autostart, files closed between writes, `os.replace` within one volume); the always-apply policies live in `11-commands.md`.

## CLI (`chatimport`)

Every command of the spec (`docs/architecture.md` §9) is implemented (`cli.py` plus
`cli_chats.py`, `cli_service.py`, `cli_data.py`). Global options: `--version`, `--root <path>`
(output folder for this run). "Service" says what happens when the service is running.

| Command | What it does | Service |
|---|---|---|
| `login` | first login: phone, code, 2FA password; creates the session | refused (needs the instance lock) |
| `dialogs` | the account's groups and channels with `chat_id`, kind, title, link | refused |
| `chats list` | every library entry, its resolution and stored record count | refused |
| `chats add <ref> [--name N]` / `chats disable\|enable <name or ref>` | edit `chats.toml` | not needed; the service rereads the file |
| `run [--once] [--chat X]` | console mode, logs to console and file; `--once` backfills or catches up every chat (or one) and exits, continuing past a failing chat | refused (one instance) |
| `tray` | normal mode with a tray icon, logs to file | refused |
| `status` | service state, disk, per-chat phase, `last_id`, records | asks the service; otherwise prints the last `_status.json` as stopped |
| `pause` / `resume [--chat X]` | stop and continue collecting; a pause survives a restart | required |
| `recheck [--chat X] [--days N]` | compare recent days with Telegram now | required |
| `trim {25,50,75} [--chat X] [--yes]` | delete the oldest share of each chat's history; asks `y/N` | sent to the service; else runs offline |
| `backfill --deeper [--chat X]` | lower `floor_id` so older history is fetched | sent; else lowers the floor offline |
| `check [--repair]` | integrity of parts, `state.json`, saved media and leftover temp files; `--repair` runs recover | sent; else runs offline |
| `export-json --chat X [--out F] [--names\|--no-names]` | one JSON array; default `<root>/_exports/<chat folder>.json`, sender names and `raw` left out unless `--names` | reads files directly |
| `set-root <path> [--move] [--yes]` | change the output folder; without `--move` asks, then chats are refetched | sent; else moves offline |

`--chat` accepts a library name, `@username`, link, numeric id, folder name or title; text is
compared through `textnorm.fold` (NFC, casefold). Exit codes: 1 error, 2 not configured.
The control registry also has `reload_config`, `shutdown` and `refetch` (tray and service
only).

## Where things live

Resolved through `platformdirs`. Windows paths shown:

| What | Where |
|---|---|
| Chat data | `<Desktop>\ChatImport\` (override: `--root`, `CHATIMPORT_ROOT`, `output.root_dir`) |
| Service files in the data root | `_status.json`, `_trim_log.jsonl`, `_unrouted_deletes.jsonl` (capped at 2 MiB), `_exports\` |
| Config, library | `%LOCALAPPDATA%\ChatImport\config.toml`, `chats.toml` |
| Session | `%LOCALAPPDATA%\ChatImport\session\chatimport.session` |
| Log | `%LOCALAPPDATA%\ChatImport\logs\chatimport.log` (UTF-8, rotating 5 MiB x 5) |
| Icon | `src/chatimport/assets/icon.png` and `icon.ico` (`chatimport.assets`); the tray draws the PNG with a state badge |
| Lock, control queue | `%LOCALAPPDATA%\ChatImport\chatimport.lock`, `control\` |

`run`, `status` and the tray warn when the data root is under OneDrive; `set-root` refuses
the application folder (it holds the session).

## Control queue

The CLI writes `<command>-<uuid>.json` atomically into `control\` and waits for
`<command>-<uuid>.result.json`. The service polls every second, claims a file by renaming it
to `.<command>-<uuid>.claimed` and only then runs it, so a command runs **at most once**; a
claim left by a crash is answered "interrupted", never re-run. Files over 64 KiB or not a
JSON object are rejected. The CLI waits 30 s, 10 min for `trim`, `check`, `deeper` and
`recheck`, 1 h for `set_root`; on a timeout after the claim it says not to repeat the command.

## CI (`.github/workflows/`)

- `ci.yml` (pushes to `main` and `chatimport`): lint (uv lock check, ruff), typecheck,
  tests on Ubuntu and Windows with Python 3.14, assistants sync and language check,
  gitleaks.
- **pyright runs on Linux in CI.** Windows-only code must sit behind a `sys.platform ==
  "win32"` check that pyright understands, or it is reported as unreachable or untyped there.
- `codeql.yml`: Python and Actions, weekly and on `main`/`chatimport`.
- Dependabot only reads the default branch (`main`); updates for this branch are manual.

## Windows notes

- Console output: the `chatimport` entry point (`cli.run`) reconfigures stdout and stderr
  to UTF-8 unless `PYTHONIOENCODING` is set, otherwise Rich help crashes on cp1252 pipes.
  Call `run`, not `app`, from scripts.
- Autostart: Task Scheduler at logon with a 1-minute delay, running
  `.venv\Scripts\pythonw.exe -m chatimport tray` (no console window).
- Close every data file after each write, or Explorer cannot delete the chat folder.
- `os.replace` is atomic only within one volume: write temp files next to the target.
  A reader holding a file (antivirus, indexer) makes `os.replace`/`unlink` fail briefly;
  `storage/fileio.py` retries them.
- Auto-trimming deletes with `os.remove`, never to the Recycle Bin, or no space is freed.
- Downloaded media get a `Zone.Identifier` stream (Mark-of-the-Web).
- If the Desktop syncs to OneDrive, set `output.root_dir` outside it.
- Prefer `uv run <tool>` over the `.venv/Scripts/*.exe` shims.
