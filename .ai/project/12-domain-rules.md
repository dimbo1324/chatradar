# Domain Rules and House Style (ChatImport)

These sharpen the universal rules for this codebase. Stricter wins.

## Python code

- Python 3.14+, full type hints, pyright strict is a gate. A `# type: ignore` or
  `# pyright: ignore` names its rule; a `# noqa` names its code and says why.
- Ruff rules in `pyproject.toml` are binding; `T20` bans `print`, `DTZ` bans naive datetimes.
- A module past roughly 500 lines is split by meaning. `cli*.py` and `tray*.py` hold
  argument parsing, menus and wiring only.
- Dependencies only through `uv add` / `uv add --dev`; `uv.lock` is committed. Only free
  open-source dependencies; a new one is added with the code that first uses it.

## Boundaries

- `telegram/mapper.py`, the storage layout and `trim` are pure or file-only: no Telethon
  client, no tray, no CLI imports. This keeps them portable into ChatRadar later.
- Telethon is touched only in `telegram/`. Everything else receives plain records.
- Collaborators come in through constructors (Telegram client, `disk_usage`, clock), so
  every component is testable without network and without a real disk.

## Data rules

- **One writer.** Only the service process writes into the `ChatImport` folder, and inside
  it only the chat's worker (or the trimmer holding that chat's lock). CLI and tray send
  commands through the control folder; the service claims each command file by renaming it
  and runs it at most once. Without a running service the CLI takes the instance lock and
  is that one writer.
- Records are JSONL, one object per line, schema field `v`. Adding a field keeps `v`;
  removing or changing meaning bumps it. History is append-only: edits and deletions are
  new `edit`/`delete` records, never rewrites.
- Files are `YYYY-MM_NNN.jsonl` (UTC month, part number); a part is the unit of storage,
  accounting and trimming. Lines inside a part ascend by `msg_id`.
- At-least-once intake plus deduplication by `msg_id` (`last_id` in `state.json`): no
  duplicates and no gaps after a crash or restart.
- `state.json` is a cache; the JSONL files are the truth. It is written atomically
  (temp file, `fsync`, `os.replace`) and rebuilt from the files when missing or broken,
  never when it exists but cannot be read now (`StateUnreadable`). A month of several parts
  is rewritten only through the journal in `storage/month_commit.py`.
- Data files are never held open between writes (Windows must be able to delete a folder).
- Trimming removes oldest first, never selectively, and raises `floor_id`; the service
  never backfills below `floor_id` on its own.
- All datetimes are timezone-aware UTC, written as ISO 8601 with `Z`.

## Telegram and privacy

- A `*.session` file is full access to an account: it lives in the application data folder,
  is never read into a transcript, logged, committed or copied.
- `api_id`/`api_hash` live only in the real `config.toml`; the repository holds
  `config.example.toml`.
- Respect FloodWait, pause between requests and chats, backfill one chat at a time
  (`runtime.BackfillSlots`, `backfill.max_parallel_chats = 1`); do not shorten pauses.
- Logs carry chat ids, message ids and counts, never message text, sender names or invite
  hashes.

## Tests

- Telegram is never called in tests: a scripted gateway (`tests/fakes.py`) replays history
  and events.
- Unit tests need no network and touch only `tmp_path`: the autouse fixture in
  `tests/conftest.py` isolates `CHATIMPORT_*` variables and the working directory.
- Mapper, chunking, recover and trim are table-driven; size thresholds are shrunk in tests
  (for example 1 KB parts) instead of writing large files.
- Fixtures in `tests/fixtures/` are anonymized: no real names, usernames or phone numbers.
  Real exports may be studied only locally and only as aggregates.

## Assistant workspaces

- `.claude/agents` and `.claude/skills` are the source; `.codex/agents|skills` are generated
  from them by `just agents`. Never edit `.codex/agents|skills` or `AGENTS.md` by hand.
- `.claude/settings.json` allowlists routine read and verification commands and denies
  destructive git operations and reading secrets. Extend the allowlist rather than routing
  around it; never remove a deny entry without owner approval.
