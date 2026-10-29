# Command Reference and Platform Notes

<!-- tier: extended -->

> **Essence.** Lookup material — the planned `chatimport` commands, where configuration and data live, CI jobs and the Windows notes (UTF-8 consoles, `pythonw` autostart, files closed between writes, `os.replace` within one volume); the always-apply policies live in `11-commands.md`.

## CLI (`chatimport`)

Implemented now: `--version`. The full set (spec, `docs/architecture.md` §9) arrives stage
by stage; move a command into "implemented" when it works.

| Command | What it does | Stage |
|---|---|---|
| `login` | first login: phone, code, 2FA password; creates the session | 0.1 |
| `dialogs` | your groups and channels with `chat_id` and links | 0.1 |
| `chats list` / `chats add <ref> [--name N]` / `chats disable\|enable` | the library | 0.1 |
| `run [--once] [--chat X]` | console mode; `--once` backfills or catches up and exits | 0.1 |
| `status` | phase, `last_id`, backfill progress, size, free space | 0.3 |
| `check [--repair]` | integrity of files and `state.json` | 0.3 |
| `trim {25,50,75} [--chat X] [--yes]` | delete the oldest share of history | 0.4 |
| `pause` / `resume [--chat X]` | stop and continue collecting | 0.4 |
| `tray` | normal mode with a tray icon | 0.5 |
| `set-root <path> [--move]` | change the output folder | 0.5 |
| `recheck [--chat X] [--days N]` | compare recent days with Telegram now | 0.6 |
| `backfill --deeper [--chat X]` | lower `floor_id` and fetch older history | 0.6 |
| `export-json --chat X [--out F]` | assemble a classic JSON array | 0.6 |

## Where things live

Resolved through `platformdirs`. Windows paths shown:

| What | Where |
|---|---|
| Chat data | `<Desktop>\ChatImport\` (override: `--root`, `CHATIMPORT_ROOT`, `output.root_dir`) |
| Config, library | `%LOCALAPPDATA%\ChatImport\config.toml`, `chats.toml` |
| Session | `%LOCALAPPDATA%\ChatImport\session\chatimport.session` |
| Logs, lock, control queue | `%LOCALAPPDATA%\ChatImport\logs\`, `chatimport.lock`, `control\` |

## CI (`.github/workflows/`)

- `ci.yml` (pushes to `main` and `chatimport`): lint (uv lock check, ruff), typecheck,
  tests on Ubuntu and Windows with Python 3.14, assistants sync and language check,
  gitleaks.
- `codeql.yml`: Python and Actions, weekly and on `main`/`chatimport`.
- Dependabot only reads the default branch (`main`); updates for this branch are manual.

## Windows notes

- Console output: the `chatimport` entry point (`cli.run`) reconfigures stdout and stderr
  to UTF-8, otherwise Rich help crashes on cp1252 pipes. Call `run`, not `app`, from scripts.
- Autostart: Task Scheduler at logon with a 1-minute delay, running
  `.venv\Scripts\pythonw.exe -m chatimport tray` (no console window).
- Close every data file after each write, or Explorer cannot delete the chat folder.
- `os.replace` is atomic only within one volume: write temp files next to the target.
- Auto-trimming deletes with `os.remove`, never to the Recycle Bin, or no space is freed.
- If the Desktop syncs to OneDrive, set `output.root_dir` outside it.
- Prefer `uv run <tool>` over the `.venv/Scripts/*.exe` shims.
