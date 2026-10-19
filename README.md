# ChatRadar

[![CI](https://github.com/dimbo1324/chatradar/actions/workflows/ci.yml/badge.svg)](https://github.com/dimbo1324/chatradar/actions/workflows/ci.yml)
[![CodeQL](https://github.com/dimbo1324/chatradar/actions/workflows/codeql.yml/badge.svg)](https://github.com/dimbo1324/chatradar/actions/workflows/codeql.yml)
![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Collects messages from messenger chats, filters out noise and answers questions **with links
to the source messages and their dates**. Digests of hot topics, "evergreen questions",
hints on whom to ask.

> **Status:** MVP without AI — import, noise filter, threads, full-text search and a web
> panel work; live Telegram sync is built and awaits its first real login. More: [product vision](docs/vision.md), [architecture](docs/architecture.md),
> [roadmap](docs/ROADMAP.md).

## How it works

```
CONNECTORS ──▶ data/raw/*.jsonl ──▶ normalize ─▶ noise ─▶ enrich ─▶ threads ─▶ index ──▶ INTERFACES
(Telegram,      (immutable          └──────────── idempotent versioned stages ───────┘   (web, bot, API)
 file imports)   source of truth)                    database (SQLite → Postgres)
```

- **Modular monolith with ports and adapters** — the domain knows nothing about Telethon,
  SQLite or FastAPI ([ADR-0001](docs/adr/0001-modular-monolith-hexagonal.md)).
- **Raw data is immutable**; the database is derived and rebuilt by `chatradar rebuild`.
- **The boundary between modules is a data format**, so any stage can be moved or rewritten.

## Quick start

You need [uv](https://docs.astral.sh/uv/), [just](https://just.systems/) and, optionally,
Docker. `python scripts/doctor.py` checks the toolchain.

```bash
git clone https://github.com/dimbo1324/chatradar.git
```

```bash
cd chatradar
```

```bash
just setup
```

```bash
cp .env.example .env
```

```bash
uv run chatradar --help
```

`uv` installs Python 3.13 from `.python-version` by itself.

### Try it without Telegram

Load four synthetic chats (Russian, Spanish, English; about 1 700 messages modelled on
real migrant chats — no real messages inside):

```bash
just demo
```

Or export your own chat in Telegram Desktop (chat menu → Export chat history → format
JSON) and import it:

```bash
uv run chatradar import tg-export path/to/result.json
```

```bash
uv run chatradar web
```

Open <http://127.0.0.1:8000> (the interface is in Russian): chats, pipeline state,
messages with filters, threads, search and the noise review page.

### Telegram

1. Register an application at [my.telegram.org](https://my.telegram.org) → `api_id`,
   `api_hash`.
2. Put them into `.env` (`CHATRADAR_TELEGRAM__API_ID`, `CHATRADAR_TELEGRAM__API_HASH`).
3. `chatradar telegram login` — the session appears in `data/sessions/`.

> **A `*.session` file is full access to the account.** It is git-ignored and pre-commit
> refuses to commit it. Keep it like a password.

### Docker

```bash
docker compose up -d --build
```

```bash
docker compose run --rm -it worker telegram login
```

Web panel: <http://127.0.0.1:8000> (loopback only), healthcheck at `/healthz`. The `./data`
directory is mounted into the containers and survives rebuilds.

## Development commands

| `just …` | What it does |
|---|---|
| `setup` | dependencies + git hook |
| `fmt` / `lint` | ruff format / ruff check |
| `typecheck` | pyright (strict) |
| `test` / `cov` | pytest / with coverage |
| `agents` / `agents-check` | regenerate / verify the AI-assistant files |
| `language` | English-only check |
| `synthetic` / `synthetic-check` | regenerate / verify the synthetic chat exports |
| `demo` | import every synthetic chat into the local database |
| `check` | everything CI checks |
| `doctor` | toolchain check |
| `migrate` / `revision "msg"` | Alembic |
| `up` / `down` / `logs` / `login` | Docker Compose |

Without `just`, run the same commands through `uv run …` (see [`justfile`](justfile)).

## CLI

```
chatradar telegram login                  # first login, interactive
chatradar chats add @some_chat            # track a chat
chatradar chats list
chatradar import tg-export ./result.json  # import a Telegram Desktop export
chatradar sync [--chat ID] [--recheck-days 7]
chatradar process [--stage noise] [--reset-stage noise]
chatradar rebuild                         # rebuild the database from data/raw
chatradar web                             # web panel
chatradar worker                          # loop: sync → process → sleep
```

## Layout

```
src/chatradar/
├── config.py        # Settings (pydantic-settings), everything from env
├── logs.py          # structlog: console in dev, JSON in prod
├── domain/          # Message, Chat, Protocol ports — no external dependencies
├── connectors/      # telegram (Telethon), tg_export (Desktop JSON)
├── storage/         # raw JSONL + db (SQLAlchemy 2.0, FTS5)
├── pipeline/        # stages: normalize, noise, enrich, threads, index
├── services/        # use cases: sync, process, search, stats
├── web/             # FastAPI JSON API + static panel (plain HTML/CSS/JS)
└── cli.py           # Typer
migrations/          # Alembic (async, batch mode on SQLite)
scripts/             # repo tooling: sync_agents, check_language, doctor
tests/{unit,integration,fixtures}
docs/                # vision, architecture, roadmap, decisions, ADR
```

## Roadmap

| Step | What | Status |
|---|---|---|
| 1 | Skeleton: uv, ruff, pyright, pytest, pre-commit, CI, `Settings` | ✅ |
| 2 | Domain and ports, Telegram Desktop JSON import, JSONL RawStore | ✅ |
| 3 | SQLAlchemy, Alembic, tables, normalization with upsert | ✅ |
| 4 | Stage runner, noise filter and enrichment | ✅ |
| 5 | Web: chats, pipeline, messages | ✅ |
| 6 | Thread grouping, FTS5, search | ✅ |
| 7 | Telethon connector, `login`, `sync`, worker | ✅ code, live login pending |
| 8 | Docker and Compose for the whole service | ✅ |

Details and status lines: [docs/ROADMAP.md](docs/ROADMAP.md).

## Data and privacy

- Messages are stored only locally in `data/` (outside git).
- Test fixtures contain anonymized messages only.
- Raw messages are never published — only summaries and links.
- No profiles of people are built (Ley 18.331 on personal data protection, Uruguay).

## AI assistants

The repository is set up for AI-assisted development, Claude Code first. Shared rules live
in [`.ai/`](.ai/README.md); [`CLAUDE.md`](CLAUDE.md) imports them, `AGENTS.md` (Codex) and
`GEMINI.md` (Gemini CLI) are their other entry points. Every session starts with an
orientation ritual over the roadmap, the decision log and `task-checklist.md`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Vulnerabilities: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
