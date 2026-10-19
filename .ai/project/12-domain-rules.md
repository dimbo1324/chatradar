# Domain Rules and House Style (ChatRadar)

These sharpen the universal rules for this codebase. Stricter wins.

## Python code

- Python 3.13+, full type hints, pyright strict is a gate. A `# type: ignore` or
  `# pyright: ignore` names its rule; a `# noqa` names its code and says why.
- Ruff rules in `pyproject.toml` are binding; `T20` bans `print`, `DTZ` bans naive datetimes.
- A module past roughly 500 lines is split by meaning. `cli.py` holds argument parsing and
  wiring only — logic lives in `services/`.
- Dependencies only through `uv add` / `uv add --dev`; `uv.lock` is committed.

## Hexagonal boundaries

- `chatradar.domain` imports nothing from Telethon, SQLAlchemy, FastAPI, Typer or aiogram.
- Adapters depend on the domain, never the other way round. Ports are `Protocol`s;
  adapters do not inherit from them.
- Dialect-specific SQL (upsert, FTS) lives only in `chatradar.storage.db`.
- The boundary between modules is a data format (JSONL, tables), not a Python object, so
  any stage can move to another process or language.

## Data rules

- Raw data in `data/raw/` is immutable and append-only; the database is derived and can be
  rebuilt with `chatradar rebuild` without calling any source.
- Sync is at-least-once: write the JSONL batch first, then advance `last_id`; the
  normalize stage upserts, so duplicates are harmless.
- Pipeline stages are idempotent and versioned. Changing a stage's rules bumps its
  `version`; a changed `content_hash` resets every later stage of that message.
- Noise is marked (`is_noise`, `noise_reason`), never deleted.
- The lexicon is data (ADR-0003). Statistics only *propose* terms (CANDIDATE); a human
  accepts them. Mining never changes the active set. Only a change of the ACTIVE set moves
  the revision, and a stage whose applied revision is behind is reset by `process`.
- A lexicon term is a phrase, never a person: no names, handles, phone numbers or message
  text in it; examples are message keys; author counts are numbers, not ids.
- All datetimes are timezone-aware UTC (`AwareDatetime`); IDs from sources are strings.
- Schema changes go through Alembic migrations only; SQLite uses `render_as_batch=True`.
- The worker writes to SQLite; the web panel reads, except term decisions and message labels (ADR-0004).

## Telegram and privacy

- A `*.session` file is full access to an account: it lives in `data/sessions/`, is never
  read into a transcript, logged, committed or copied.
- Respect FloodWait, pause between chats, keep load low on a new account.
- Do not store phone numbers or other personal data in dedicated fields; do not build
  per-person profiles.
- Logs carry IDs and counts, never message text.

## Tests

- Telegram is never called in tests: a fake `Connector` replaces it.
- Unit tests need no network and no real `data/`: the autouse fixture in
  `tests/conftest.py` isolates env and the working directory.
- Mappers, noise rules and thread grouping are pure functions with table-driven tests;
  every misclassification found by hand becomes a new row.
- Fixtures in `tests/fixtures/` are anonymized: no real names, usernames or phone numbers.
- Real chat exports may be studied only locally and only as aggregates (rates, lengths,
  topics); no real message, name or username is ever copied into the repository or a
  transcript. New realistic data goes through `scripts/generate_synthetic.py` and its
  invented phrase bank.

## Assistant workspaces

- `.claude/agents` and `.claude/skills` are the source; `.codex/agents|skills` are generated
  from them by `just agents`. Never edit `.codex/agents|skills` or `AGENTS.md` by hand.
- `.claude/settings.json` allowlists routine read and verification commands and denies
  destructive git and Docker volume operations and reading secrets. Extend the allowlist
  rather than routing around it; never remove a deny entry without owner approval.
