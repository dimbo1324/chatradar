# Contributing

## Environment

```bash
just setup        # uv sync + pre-commit install
just doctor       # read-only toolchain check
just check        # what CI checks: lint, types, tests, agents sync, language
```

## Branches and commits

- This line of work lives on branch `chatimport`; `main` holds ChatRadar and is not touched
  from here. Task branches (`feat/…`, `fix/…`, `chore/…`, `docs/…`) start from `chatimport`
  and merge back with `git merge --ff-only` after a green `just check`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(writer): open the next part at the size threshold`.
- Small changes, one idea per change.

## Code rules

- **Strict types** (pyright strict). `Any` only at the boundary with untyped libraries.
- **Telethon only in `chatimport.telegram`.** Mapper, storage and trim import no client,
  CLI or tray, so they can move into ChatRadar later. The module map is in
  `.ai/project/10-project-map.md` and `docs/architecture.md` §12.
- **One writer:** only the service writes data files; CLI and tray send commands, which the
  service runs at most once. Without a running service the CLI takes the instance lock.
- **Small modules:** split a module by meaning before it passes about 500 lines; `cli*.py`
  and `tray*.py` only parse arguments, build menus and call one service function.
- **Append-only history:** edits and deletions are new records.
- **Atomic writes** through `storage/fileio.py`; a month of several parts only through
  `storage/month_commit.py`; no file stays open between writes.
- **Datetimes are always timezone-aware UTC.** Ruff (`DTZ`) catches naive ones.
- **English only** in tracked files; `just language` enforces it. Non-ASCII test text is
  built with `chr()` or `\u` escapes; real Russian chat data may live only in anonymized
  fixtures under `tests/fixtures/` (none yet).
- **Windows-only code** sits behind `sys.platform == "win32"`: CI runs pyright on Linux.

## Tests

- Table-driven tests for the mapper, part splitting, recovery and trimming.
- **Telegram is never called from tests** — the scripted gateway in `tests/fakes.py`
  replays history and events.
- Coverage is 100 % line and branch; keep it there for the modules you touch.
- Thresholds shrink in tests (1 KB parts, a fake `disk_usage`, a fake clock).
- Fixtures are **anonymized**: no real names, phone numbers or usernames.

## AI assistants

Rules for assistants live in `.ai/` (see `.ai/README.md`). After editing a module, an agent
or a skill run `just agents` and commit the regenerated `AGENTS.md` and `.codex/`.

## Decisions

Owner decisions go to `docs/decisions.md`; a significant architecture decision gets a short
ADR in `docs/adr/`. Changes are listed in [CHANGELOG.md](CHANGELOG.md).
