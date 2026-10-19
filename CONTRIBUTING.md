# Contributing

## Environment

```bash
just setup        # uv sync + pre-commit install
just doctor       # read-only toolchain check
just check        # what CI checks: lint, types, tests, agents sync, language
```

## Branches and commits

- `main` is always green; work happens on `feat/…`, `fix/…`, `chore/…`, `docs/…` branches,
  merged into `main` with `git merge --ff-only` after a green `just check`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(noise): rule for Spanish gratitude messages`.
- Small changes, one idea per change.

## Code rules

- **Strict types** (pyright strict). `Any` only at the boundary with untyped libraries.
- **Pure domain:** `chatradar.domain` imports no Telethon, SQLAlchemy or FastAPI.
- **Database dialect** (upsert, FTS) only in `chatradar.storage.db`.
- **CLI, web and bot are thin wrappers** over `chatradar.services`; no logic in them.
- **Datetimes are always timezone-aware UTC.** Ruff (`DTZ`) and pydantic (`AwareDatetime`)
  catch naive ones.
- **Stages are idempotent.** Changed a stage's rules — bump its `version`.
- **Schema changes only through migrations:** `just revision "description"`.
- **English only** in tracked files; `just language` enforces it. Russian and Spanish
  data (fixtures, lexicons) live in the paths allowed by `scripts/check_language.py`.

## Tests

- `tests/unit` — pure functions: mappers, noise rules, thread grouping. Table-driven
  ("message → expected reason"); every misclassification found by hand becomes a new row.
- `tests/integration` — the whole pipeline on in-memory SQLite.
- **Telegram is never called from tests** — a fake `Connector` replaces it.
- Fixtures in `tests/fixtures` are **anonymized**: no names, phone numbers or usernames.

## AI assistants

Rules for assistants live in `.ai/` (see `.ai/README.md`). After editing a module, an agent
or a skill run `just agents` and commit the regenerated `AGENTS.md` and `.codex/`.

## Architecture decisions

A significant decision (a new dependency, a storage change, a new service) gets a short ADR
in `docs/adr/`; owner decisions go to `docs/decisions.md`.

## Releases

The version lives in `pyproject.toml` (SemVer). A `vX.Y.Z` tag makes GitHub Actions build
the image into GHCR and create a GitHub Release with generated notes. Changes are listed in
[CHANGELOG.md](CHANGELOG.md).
