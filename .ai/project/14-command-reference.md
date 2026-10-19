# Command Reference and Platform Notes

<!-- tier: extended -->

> **Essence.** Lookup material — CLI commands, configuration variables, Docker usage, CI jobs and the Windows notes (UTF-8 consoles, ASCII-only `alembic.ini`, Docker Desktop started by the owner, `httpx2` for the Starlette test client); the always-apply policies live in `11-commands.md`.

## CLI (`chatradar`)

| Command | What it does |
|---|---|
| `telegram login` | interactive first login; session in `data/sessions/` |
| `chats add <@username, link or id>` / `chats list` | track a chat / list known chats |
| `import tg-export <result.json> [--username U] [--no-process]` | Desktop JSON import, then process |
| `sync [--chat ID]... [--recheck-days N]` | fetch new messages into `data/raw/`, then process |
| `process [--stage S] [--reset-stage S]` | run pipeline stages |
| `rebuild` | clear derived data and re-map every raw record, then process |
| `web [--host] [--port]` | the panel (uvicorn) |
| `worker` | loop: migrate, sync (if Telegram is configured), process, sleep |

Telegram commands exit with code 2 and a hint when `TELEGRAM__API_ID`/`API_HASH` are
missing. Every command applies migrations when it opens the database.

## Configuration

`Settings` in `src/chatradar/config.py`; prefix `CHATRADAR_`, nested with `__`, empty
values fall back to defaults. Template: `.env.example`. Key variables: `ENV` (`dev`/`prod`),
`LOG_LEVEL`, `DATA_DIR`, `DATABASE_URL` (empty → SQLite in `DATA_DIR`),
`TELEGRAM__API_ID`, `TELEGRAM__API_HASH`, `TELEGRAM__SESSION_NAME`,
`WORKER__SYNC_INTERVAL_HOURS`, `WORKER__RECHECK_DAYS`, `WEB__HOST`, `WEB__PORT`.

## Docker

- `docker compose up -d --build` starts `web` (127.0.0.1:8000, healthcheck `/healthz`) and
  `worker`; `./data` is mounted at `/app/data`.
- `docker compose run --rm -it worker telegram login` for the first login.
- The image runs as uid 1000 with `CHATRADAR_ENV=prod` (JSON logs). `uv` is pinned in the
  `Dockerfile` (`UV_VERSION`); the build context is an allowlist in `.dockerignore` — a new
  file the build needs (as `LICENSE` once was) must be added there.
- Postgres: uncomment `db` in `compose.yaml`, set `CHATRADAR_DATABASE_URL`, run
  `alembic upgrade head`, then `chatradar rebuild`.

## CI (`.github/workflows/`)

- `ci.yml`: lint (uv lock check, ruff), typecheck, tests on Ubuntu 3.13/3.14 and Windows
  3.13 with migrations on an empty SQLite, assistants sync and language check, gitleaks,
  Docker build and smoke (`--version`, `/healthz`).
- `codeql.yml`: Python and Actions, weekly and on `main`.
- `release.yml`: on `v*.*.*` tags, multi-arch image to `ghcr.io/dimbo1324/chatradar` with
  provenance and SBOM, then a GitHub Release with generated notes.
- Dependabot: uv, GitHub Actions, Docker, pre-commit; Telethon majors are ignored.

## Windows notes

- Console output: the `chatradar` entry point (`cli.run`) reconfigures stdout and stderr to
  UTF-8, otherwise Rich help crashes on cp1252 pipes. Call `run`, not `app`, from scripts.
- `alembic.ini` must stay ASCII-only: configparser reads it in the locale encoding.
- Docker Desktop is started by the owner. An agent session finds the daemon down as
  `npipe:////./pipe/dockerDesktopLinuxEngine ... cannot find the file`; report it and rely
  on the CI Docker job instead of starting Docker Desktop from the session.
- `tzdata` is a Windows-only dependency so `zoneinfo` (Alembic `timezone = UTC`) works.
- Starlette's test client needs `httpx2`; plain `httpx` raises a deprecation error, which
  `filterwarnings = error` turns into a failure.
- Prefer `uv run <tool>` over the `.venv/Scripts/*.exe` shims.
