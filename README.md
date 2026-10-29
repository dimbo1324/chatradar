# ChatImport

A local background service that keeps the full text history of chosen Telegram groups and
channels on your disk as JSONL. It backfills each chat once, then appends new messages in
small batches, rechecks the last 7 days daily for edits and deletions, and never lets itself
fill the disk.

> **Status: stage 0.0.** The repository is prepared; the service is not written yet. Plan:
> [docs/ROADMAP.md](docs/ROADMAP.md). Design: [docs/architecture.md](docs/architecture.md).
>
> This is branch `chatimport` of the ChatRadar repository: a parallel line of work that will
> later merge with ChatRadar (on `main`).

## How it will work

- Tracks **only** the groups and channels listed in `chats.toml` (links, @usernames, ids or
  exact titles). Private dialogs are never read.
- Writes `ChatImport/<chat>_<chat_id>/YYYY-MM_NNN.jsonl` (the Desktop by default): one
  JSON object per line, month files split into 20 MB parts.
- Delete a chat folder → it is fetched again. `chatimport trim 50` → the oldest half of
  every chat is removed. Under 15 GB free → the oldest parts are removed automatically.
- Runs as its own session of your Telegram account (Telethon); Telegram Desktop may stay
  closed.

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14), git,
[just](https://just.systems/).

```bash
just setup        # uv sync + pre-commit hook
just doctor       # read-only toolchain check
just check        # lint, pyright strict, tests, rules sync, language
uv run chatimport --version
```

Templates for the real configuration: [config.example.toml](config.example.toml) and
[chats.example.toml](chats.example.toml). The real files live in the application data
folder (`%LOCALAPPDATA%\ChatImport\` on Windows) and never reach git.

## Privacy

The Telegram session file is full access to your account; it stays in the application data
folder. Sender names are personal data: the archive is for your own local use. See
[SECURITY.md](SECURITY.md).

## License

MIT.
