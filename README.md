<p align="center">
  <img src="src/chatimport/assets/icon.png" alt="ChatImport" width="160">
</p>

# ChatImport

A local background service that keeps the full text history of chosen Telegram groups and
channels on your disk as JSONL. It backfills each chat once, then appends new messages in
small batches, rechecks the last 7 days daily for edits and deletions, and never lets itself
fill the disk.

> **Status: the service is implemented (stages 0.1–0.7) and hardened, but has not yet run
> against a real Telegram account.** Everything is tested against a scripted fake of
> Telegram (3155 tests, 100 % line and branch coverage). The next step is the owner's live
> check: `login`, one small chat, then all of them. Plan: [docs/ROADMAP.md](docs/ROADMAP.md).
> Design: [docs/architecture.md](docs/architecture.md).
>
> This is branch `chatimport` of the ChatRadar repository: a parallel line of work that will
> later merge with ChatRadar (on `main`).

## How it works

- Tracks **only** the groups and channels listed in `chats.toml` (links, @usernames, ids or
  exact titles). Private dialogs are never read; the service never joins a chat and never
  sends anything.
- Writes `ChatImport/<chat>_<chat_id>/YYYY-MM_NNN.jsonl` (the Desktop by default): one JSON
  object per line, month files split into 20 MB parts. Folder names are ASCII (Cyrillic
  titles are transliterated).
- Delete a chat folder → it is fetched again. `chatimport trim 50` → the oldest half of
  every chat is removed. Under 15 GB free → the oldest parts are removed automatically and
  history downloads stop until `chatimport backfill --deeper`.
- Runs as its own session of your Telegram account (Telethon); Telegram Desktop may stay
  closed. History is downloaded one chat at a time, with pauses.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14), git,
[just](https://just.systems/) for development.

1. `uv sync`
2. Copy [config.example.toml](config.example.toml) to `%LOCALAPPDATA%\ChatImport\config.toml`
   and set `api_id` and `api_hash` from <https://my.telegram.org> (API development tools).

```bash
uv run chatimport login                       # phone, code, 2FA password; once
uv run chatimport dialogs                     # your groups and channels with chat_id
uv run chatimport chats add https://t.me/example_group --name example
uv run chatimport chats list                  # does every entry resolve?
uv run chatimport run --once --chat example   # fetch one chat and exit
uv run chatimport tray                        # normal operation, tray icon
uv run chatimport status                      # what the service is doing
```

Other commands: `run` (console mode), `pause`/`resume`, `recheck`, `trim 25|50|75`,
`backfill --deeper`, `check [--repair]`, `export-json --chat X`, `set-root <path> --move`.
`uv run chatimport --help` lists them; details in
[.ai/project/14-command-reference.md](.ai/project/14-command-reference.md). Autostart on
Windows: Task Scheduler at logon running `.venv\Scripts\pythonw.exe -m chatimport tray`
([docs/architecture.md](docs/architecture.md) §14).

## Getting your Telegram API keys

Telegram gives every program its own free `api_id` and `api_hash`. You create them once. The
window's first-run wizard and its Telegram settings card have a "How do I get these keys?"
guide with the same steps.

1. Open <https://my.telegram.org> in any browser.
2. Enter the phone number of your Telegram account in international format, for example
   `+598 99 123 456`.
3. Telegram sends a login code inside the Telegram app on your phone (not as an SMS). Enter it.
4. Click "API development tools".
5. Fill in the form: App title is any text in Latin letters; Short name is 5 to 32 Latin letters
   or digits; Platform is Desktop; URL and Description may stay empty.
6. Click "Create application".
7. Copy `api_id` (a number) and `api_hash` (32 hexadecimal characters) into the wizard, the
   Settings page or `config.toml`.

If the site answers with "ERROR" when you create the application, turn off any VPN, proxy and
ad blocker for the site, try another browser or a private window, use Latin letters and digits
only in every field, and try again after some time.

Keep `api_hash` secret: anyone who has it can act as an application on your account. ChatImport
stores it only in `config.toml` on your computer.

## Where things live (Windows)

| What | Where |
|---|---|
| Chat data | `<Desktop>\ChatImport\` (change with `chatimport set-root <path> --move`, `--root`, `CHATIMPORT_ROOT` or `output.root_dir`) |
| Config and library | `%LOCALAPPDATA%\ChatImport\config.toml`, `chats.toml` |
| Telegram session | `%LOCALAPPDATA%\ChatImport\session\chatimport.session` |
| Log | `%LOCALAPPDATA%\ChatImport\logs\chatimport.log` (rotating) |
| Exports | `<data root>\_exports\<chat folder>.json` |
| Icon | `src/chatimport/assets/icon.png` (tray, README) and `icon.ico` (shortcuts, future executable) |

The real config and library never reach git; the repository holds only the templates.

## Privacy

- The Telegram session file is full access to your account; it stays in the application
  data folder. If it leaks, terminate it in Telegram → Settings → Devices.
- Sender names are personal data: the archive is for your own local use.
  `export-json` leaves names out unless you pass `--names`.
- If your Desktop syncs to OneDrive, the archive leaves the machine: `run`, `status` and the
  tray warn about it; move the data with `chatimport set-root`.
- Logs carry ids and counts, never message text, names or invite links.

See [SECURITY.md](SECURITY.md).

## Development

```bash
just setup        # uv sync + pre-commit hook
just doctor       # read-only toolchain check
just check        # lint, pyright strict, tests, rules sync, language
```

## License

MIT.
