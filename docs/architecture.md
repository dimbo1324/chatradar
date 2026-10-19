# ChatRadar — MVP architecture without AI

Version of 2026-10-18. Stage: collecting and processing messages (a "plain service"); AI is
added later. MVP language: Python. Re-check current library versions before each step.

---

## 0. How automatic export from Telegram works

**Principle.** A manual export in Telegram Desktop is ordinary requests to the Telegram API
(the MTProto protocol), just behind a button. To automate it you write your own client that
logs in as a user and makes the same requests. A bot does not fit: it cannot see history
from before it was added. Telegram Desktop has no command line for exporting, so it cannot
be scheduled.

**Tools:**
- **Telethon** (Python) — the main choice: a mature library with good documentation that
  handles FloodWait itself.
- Pyrogram — the original is no longer maintained; only forks live on. Do not use.
- TDLib — Telegram's official C++ library; overkill for the MVP.
- Ready-made CLIs (for example `tdl` in Go) — to take a quick look at the data.

**How Telethon works:**
1. Register an application at my.telegram.org and get `api_id` and `api_hash`.
2. First login: phone number, the code from Telegram, the 2FA password. A `*.session` file
   is created; later logins need no code. **The session file = full access to the
   account**: not in git, keep it like a password.
3. Chats: public ones by `@username`, private ones through `get_dialogs` if the account is
   a member.
4. History: `iter_messages`; the library pages through it 100 at a time.
5. Incremental sync: keep `last_id` per chat and request `min_id=last_id`.
6. Run on a schedule.

Minimal example (Telethon 1.x):

```python
import asyncio
from telethon import TelegramClient

client = TelegramClient("collector", API_ID, API_HASH, flood_sleep_threshold=120)

async def fetch(chat, last_id=0):
    msgs = []
    async for m in client.iter_messages(chat, min_id=last_id, reverse=True):
        msgs.append({
            "id": m.id,
            "date": m.date.isoformat(),
            "author": m.sender_id,
            "text": m.message,
            "reply_to": m.reply_to.reply_to_msg_id if m.reply_to else None,
            "has_media": m.media is not None,
        })
    return msgs

async def main():
    async with client:          # the first run asks for the phone and the code
        msgs = await fetch("some_public_chat")
        print(len(msgs), msgs[-1] if msgs else None)

asyncio.run(main())
```

`reverse=True` yields messages from oldest to newest, so the last processed one has the
highest id.

**Nuances:**
- Incremental sync by `min_id` does not see edits and deletions. The simple fix: once a day
  refetch the last 3–7 days. The full fix: a persistent connection and the `NewMessage`,
  `MessageEdited`, `MessageDeleted` events.
- Links: public chat — `t.me/<username>/<id>`; private supergroup —
  `t.me/c/<id without -100>/<message id>` (opens only for members).
- In forums (groups with topics) `reply_to` may point at the topic rather than a message —
  check on your own chats.
- Media: only mark the type at first; download (`download_media`) later and selectively.
- `client.takeout(...)` — Desktop's export mode with softer limits for a large initial
  download. Not needed for 5–10 chats.

**Main or separate account:**

| | Main account | Separate account |
|---|---|---|
| Pros | Already in every chat, including private ones; an old account raises less suspicion | The risk is isolated from the personal account |
| Cons | It gets the restrictions if overloaded; the session = access to the personal account | Needs a second number; private chats must be joined again; new accounts are banned more often through the API |

For experiments and periodic export of 5–10 chats the main account is fine, without
aggressive load. A separate account is for when the collector moves to a server and runs
around the clock, or when the bot starts serving other people. Let a new account "live" a
few days as an ordinary one and make the first export slowly.

---

## 1. Architecture principles

1. **A modular monolith with ports and adapters (hexagonal architecture).** At the center
   are the domain model (`Message`, `Thread`, `Chat`) and "port" interfaces: message source,
   raw data store, message repository, search index. Telethon, SQLite and FastAPI are
   adapters; the domain does not know them. SQLite → Postgres = a new repository adapter;
   the pipeline does not change.
2. **Raw data is immutable and kept apart from the database.** Telegram → JSONL in
   `data/raw/`. The database is derived: it can be deleted and rebuilt with `rebuild`
   without calling Telegram.
3. **A pipeline of idempotent, versioned stages.** Any stage can be rerun; changed rules
   recompute only what is needed.
4. **The boundary between modules is a data format, not Python objects.** Then any stage can
   be rewritten in Go or Rust: it reads and writes the same tables and files.
5. **Configuration through environment variables**; secrets only in `.env` (not in git).

---

## 2. Stack

| Task | Tool | Why |
|---|---|---|
| Python | 3.13 (3.14 if every dependency builds) | |
| Project, dependencies, venv | **uv** | Fast, lock file, convenient in Docker |
| Linter and formatter | **ruff** | Replaces flake8, isort, black |
| Types | **pyright** or **mypy** (strict) | Strict typing |
| Tests | **pytest**, pytest-asyncio | |
| Models and config | **pydantic v2**, **pydantic-settings** | Validation at the edges, config from env |
| Database | **SQLAlchemy 2.0** (async) + **Alembic** | One abstraction for SQLite and Postgres, migrations |
| Drivers | `aiosqlite` → later `asyncpg` | Switching databases = changing `DATABASE_URL` |
| Telegram | **Telethon 1.x** | The stable main branch; v2 has a different API — check its status before starting |
| CLI | **Typer** | |
| Web | **FastAPI** + **Jinja2** + **HTMX** | A simple interface without a separate frontend |
| Logs | **structlog** | Structured logs, JSON in Docker |
| Text language | **lingua-py** | Tells ru from es even on short phrases |
| Containers | Docker + **docker compose** | |
| Quality | pre-commit, GitHub Actions | |

**Deliberately not used at the start:** Celery, Redis, Kafka, React, microservices. The
architecture allows adding them later without rewriting the core.

---

## 3. Repository layout

```
chatradar/
├── pyproject.toml          # dependencies, ruff/pyright/pytest settings
├── uv.lock
├── .env.example            # config template (in git); .env is not
├── .gitignore
├── Dockerfile
├── compose.yaml
├── alembic.ini
├── justfile                # short commands: just test, just sync, just up
├── migrations/             # Alembic
├── data/                   # ALL of it git-ignored
│   ├── raw/telegram/<chat_id>/2026-10-18T23-50.jsonl
│   ├── sessions/collector.session
│   └── chatradar.db
├── src/chatradar/
│   ├── config.py           # Settings (pydantic-settings)
│   ├── domain/
│   │   ├── models.py       # Message, Thread, Chat, enums
│   │   └── ports.py        # Protocol interfaces
│   ├── connectors/
│   │   ├── telegram/       # Telethon: client.py, mapper.py
│   │   └── tg_export/      # Telegram Desktop JSON import
│   ├── storage/
│   │   ├── raw_jsonl.py    # file-based RawStore
│   │   └── db/             # engine.py, tables.py, repositories.py, search_fts5.py
│   ├── pipeline/
│   │   ├── base.py         # Stage interface, runner
│   │   ├── normalize.py
│   │   ├── noise.py
│   │   ├── enrich.py
│   │   ├── threads.py
│   │   └── index.py
│   ├── services/           # use cases: sync, process, search, stats
│   ├── web/                # FastAPI: app.py, routes.py, templates/
│   └── cli.py              # Typer: the entry point
└── tests/
    ├── fixtures/           # anonymized real messages
    ├── unit/
    └── integration/
```

`.gitignore` (the essentials):

```
data/
*.session
*.session-journal
.env
.venv/
```

The session and the exports live inside the project, but not in git. In Docker the `data/`
directory is mounted as a volume.

---

## 4. Domain model and ports

```python
# domain/models.py
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict

class Source(StrEnum):
    TELEGRAM = "telegram"
    WHATSAPP_EXPORT = "whatsapp_export"

class MediaType(StrEnum):
    NONE = "none"; PHOTO = "photo"; VOICE = "voice"; VIDEO_NOTE = "video_note"
    DOCUMENT = "document"; STICKER = "sticker"; OTHER = "other"

class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Source
    chat_id: str            # strings: messengers use different id types
    msg_id: str
    author_id: str | None
    date: datetime          # always UTC, timezone-aware
    text: str
    reply_to: str | None
    topic_id: str | None    # topic in Telegram forums
    media_type: MediaType
    is_forward: bool
    is_service: bool        # "joined the group" and similar
    edited_at: datetime | None
    link: str | None
    content_hash: str       # hash of meaningful fields, to catch edits
```

```python
# domain/ports.py
from typing import Protocol, AsyncIterator

class Connector(Protocol):
    source: Source
    async def list_chats(self) -> list[ChatInfo]: ...
    def fetch(self, chat_id: str, since_id: str | None) -> AsyncIterator[RawRecord]: ...

class RawStore(Protocol):
    async def append(self, source: Source, chat_id: str, records: list[RawRecord]) -> None: ...
    def read(self, source: Source, chat_id: str) -> AsyncIterator[RawRecord]: ...

class MessageRepository(Protocol):
    async def upsert_many(self, msgs: list[Message]) -> UpsertResult: ...
    async def pending_for(self, stage: str, version: int, limit: int) -> list[StoredMessage]: ...
    async def mark(self, stage: str, version: int, updates: list[StageResult]) -> None: ...

class SearchIndex(Protocol):
    async def index(self, items: list[Indexable]) -> None: ...
    async def search(self, query: str, filters: SearchFilters) -> list[Hit]: ...
```

`Protocol` is structural typing: an adapter does not inherit from it, it only needs the
methods. In tests an in-memory class replaces SQLite.

---

## 5. Pipeline stages

```
export → raw data → normalization → noise filter → enrichment → thread grouping → index → (AI)
```

### Stage 0. Collection (sync)

Task: fetch new messages into `data/raw/`.

For each chat:
1. Read `last_id` from the `sync_state` table.
2. `iter_messages(chat, min_id=last_id, reverse=True)`, accumulating batches of 500.
3. Append each batch to this run's JSONL file.
4. **Only after the file is written** update `last_id` in the database.
5. Pause 2–5 seconds between chats.

If the process dies between steps 3 and 4, some messages are fetched again — there are no
duplicates thanks to the upsert in the next stage (at-least-once delivery + idempotent
processing).

Edits and deletions: once a day refetch the last 7 days (`offset_date`); `content_hash`
catches the changes.

Raw record format:

```json
{"source":"telegram","chat_id":"-100123","fetched_at":"2026-10-18T23:50:00Z","payload":{"...": "m.to_dict()"}}
```

`m.to_dict()` contains `datetime` and `bytes` — `json.dumps` needs its own `default=`
(datetime → ISO, bytes → base64).

The first login is a separate interactive command `chatradar telegram login`; the session
lives in `data/sessions/`.

The same `Connector` port is implemented by the Telegram Desktop JSON import, so the whole
pipeline can be debugged without connecting to Telegram.

### Stage 1. Normalization (normalize)

Task: raw records → `Message` → upsert into `messages`.

- **The mapper is a pure function** `telethon_dict → Message`, without I/O. The prime
  candidate for tests.
- Dates → UTC; text → Unicode NFC, trimmed whitespace, collapsed repeated newlines. The
  original is kept in `text_raw`.
- Link: `t.me/<username>/<id>` or `t.me/c/<id without -100>/<id>`.
- **Upsert with a hash check:** new → insert; `content_hash` changed → update and **reset
  the versions of every later stage**; same hash → do nothing.

Upsert in SQLAlchemy differs for SQLite and Postgres (`sqlite.insert` /
`postgresql.insert` with `on_conflict_do_update`). This is the only place where code knows
the dialect, and it is hidden in the repository.

### Stage 2. Noise filter (noise)

Task: set `is_noise` and `noise_reason`. **Delete nothing.**

A list of rules, each a function `(msg, context) -> reason | None`; the first match wins:

```python
RULES: list[Rule] = [
    service_message,      # service events
    sticker_or_emoji_only,
    gratitude,            # "thanks", "gracias", "+", "👍" — from a dictionary
    short_without_value,  # < 15 characters AND not an answer to a question
    duplicate,            # the normalized text's hash was seen within 30 days
    spam_patterns,        # links + "easy money / DM me", bot messages
]
NOISE_VERSION = 3          # change the rules → bump it
```

- `context` gives access to the message being replied to: "yes" as an answer to a
  question ≠ "yes" as flood.
- Dictionaries and thresholds live in configuration (YAML or constants), not inside rule
  code.
- Table-driven tests: "message → expected reason". Every miss found by hand becomes a new
  test row.
- On the web — a page "random 100 from noise / from non-noise" for manual review.

### Stage 3. Enrichment (enrich)

Cheap features without AI, only for `is_noise = false`:
- `lang`: ru / es / en / mixed (lingua-py; texts shorter than ~20 characters → `unknown`);
- `is_question`: "?" or question words in ru and es;
- `urls`: extracted links;
- `has_mention`: @username mentions.

Do not extract phone numbers or personal data into separate fields.

### Stage 4. Thread grouping (threads)

Task: assign every message a `thread_id`.

1. **Reply links → connected components** (union-find).
2. **Messages without a reply** join the previous thread of the same chat (and the same
   forum topic) if the gap is shorter than `GAP` (start with 30 minutes). Otherwise — a new
   thread.
3. **Stable id:** `thread_id = f"{chat_id}:{root_msg_id}"`, the root being the earliest
   message.
4. **Incremental:** only the tail of the chat is recomputed — new messages plus a 2-day
   overlap.

Result: the `threads` table (id, chat, start, end, message count, `has_question`) and
`messages.thread_id`.

The stage is isolated behind an interface — later another algorithm (for example with
embeddings) can be plugged in and compared.

### Stage 5. Indexing (index)

- SQLite: FTS5 over `messages.text` and over the joined thread text. For Russian, without
  morphology at first — prefix search (`kvartir*`).
- Postgres later: `tsvector` + a GIN index.
- Both implementations sit behind the `SearchIndex` port.
- Later: embeddings, `sqlite-vec` → `pgvector`.

### Stage orchestration

```python
class Stage(Protocol):
    name: str            # "noise"
    version: int         # NOISE_VERSION
    depends_on: str      # "normalize"
    async def process(self, batch: list[StoredMessage]) -> list[StageResult]: ...
```

Runner:

```
for each stage in order:
    while there are messages where <stage>_v IS NULL or < version
                         and the previous stage is done:
        take a batch (500) → process → write the result and the version in one transaction
```

`messages` has the columns `normalize_v, noise_v, enrich_v, thread_v, index_v`. The
pipeline state is visible in one SQL query.

When scaling, the runner is replaced by a queue (Redis Streams, NATS); the `Stage`
interface stays.

---

## 6. Database and the SQLite → Postgres move

Starting schema:

```
chats         (source, chat_id, title, username)
sync_state    (source, chat_id, last_id, last_sync_at)
messages      (source, chat_id, msg_id, author_id, date, text, text_raw, reply_to, topic_id,
               media_type, is_forward, is_service, edited_at, link, content_hash,
               lang, is_question, is_noise, noise_reason, thread_id,
               normalize_v, noise_v, enrich_v, thread_v, index_v)
threads       (thread_id, source, chat_id, started_at, ended_at, root_msg_id, msg_count, has_question)
messages_fts  (FTS5)
```

- **SQLAlchemy 2.0 Core** for the pipeline (bulk upserts). ORM in the web part, where it is
  more convenient.
- **Alembic** from day one. For SQLite — `render_as_batch=True` (otherwise `ALTER TABLE`
  does not work).
- **SQLite PRAGMAs** on connect: `journal_mode=WAL; foreign_keys=ON; busy_timeout=5000;
  synchronous=NORMAL`. WAL lets the web read while the worker writes.
- **One process writes to SQLite** (the worker); the web only reads. With Postgres this
  limit goes away.
- Dialect-dependent code (upsert, FTS) — only in `storage/db/`.

Moving to Postgres:
1. add a `db` service to compose;
2. change `DATABASE_URL`;
3. `alembic upgrade head`;
4. `chatradar rebuild` — rebuild the database from the raw JSONL.

---

## 7. Web interface (FastAPI + HTMX)

The goal is to see what happens inside. It is a debug panel, not a product.

1. **Chats:** list, message count, last sync, a "sync" button.
2. **Pipeline:** how many messages are at each stage, how many wait, rule versions.
3. **Messages:** a table with filters (chat, date, language, noise, noise reason, question),
   loaded through HTMX.
4. **Thread:** the thread's messages as a feed indented by reply, with Telegram links.
5. **Search:** query → found threads.
6. **Filter review:** random 100 from noise and from non-noise.

HTMX: only Python and HTML templates, no frontend build. The future web dashboard is
separate, in React/Next.js, over the same FastAPI as a JSON API.

The future Telegram bot is an interface adapter just like the web: it calls the same
`search`, `stats` and `digest` services. The core does not have to change.

---

## 8. CLI

```
chatradar telegram login                  # first login, interactive
chatradar chats add @montevideo_ru        # add a chat to the list
chatradar chats list
chatradar import tg-export ./result.json  # import a Desktop export
chatradar sync [--chat ID] [--recheck-days 7]
chatradar process [--stage noise] [--reset-stage noise]
chatradar rebuild                         # the database again from data/raw
chatradar web                             # uvicorn
chatradar worker                          # loop: sync → process → pause
```

Every command is a thin wrapper over a function in `services/`. There is no logic in the CLI.

---

## 9. Docker

**Dockerfile** (multi-stage with uv):

```dockerfile
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
WORKDIR /app
RUN useradd -m app
COPY --from=builder --chown=app /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER app
ENTRYPOINT ["chatradar"]
```

Pin the `uv:latest` tag to a concrete version in the project (done: `UV_VERSION` in the
`Dockerfile`).

**compose.yaml:**

```yaml
services:
  web:
    build: .
    command: web --host 0.0.0.0 --port 8000
    ports: ["127.0.0.1:8000:8000"]   # loopback only
    env_file: .env
    volumes: ["./data:/app/data"]

  worker:
    build: .
    command: worker
    env_file: .env
    volumes: ["./data:/app/data"]
    restart: unless-stopped

  # later:
  # db:
  #   image: postgres:17
  #   volumes: ["pgdata:/var/lib/postgresql/data"]
```

First Telegram login:

```
docker compose run --rm -it worker telegram login
```

The session appears in `./data/sessions/` and survives container rebuilds.

At start `worker` runs `alembic upgrade head`, then an endless loop: a sync every N hours,
processing after every sync. For the MVP an `asyncio` loop with `sleep` is enough, without a
separate scheduler.

---

## 10. Code quality

- **pyproject.toml:** ruff with the rules `E, F, I, UP, B, SIM, ASYNC, RUF` (and more, see
  the file); pyright in strict mode.
- **pre-commit:** ruff, ruff-format, pyright, a ban on committing `.env` and `*.session`.
- **Tests:**
  - unit — the mapper, noise rules, the grouping algorithm, on anonymized real fixtures;
  - integration — the whole pipeline on in-memory SQLite;
  - Telegram is never called in tests; a fake `Connector` replaces it.
- **CI** (GitHub Actions): lint → typecheck → tests on every push.
- **Logs:** structlog; every event carries `stage`, `chat_id`, `count`, `duration_ms`.
- **Config:** one `Settings` class (pydantic-settings); `.env.example` in the repository,
  `.env` not.

---

## 11. About Go, C++ and Rust

The project's bottlenecks are **Telegram API limits** and **LLM speed and cost**, not
Python. A rule-based filter handles hundreds of thousands of messages in seconds. Rewrite in
another language only when profiling shows a concrete hot spot. Candidates:
- local embedding computation (but there is C++/Rust inside the libraries already);
- a high-load collector for thousands of chats — Go fits.

The boundary between modules is JSONL and database tables, so a stage can be rewritten on
its own. Not worth doing in advance.

---

## 12. Implementation order

| Step | What to do | Result |
|---|---|---|
| 1 | Skeleton: uv, ruff, pyright, pytest, pre-commit, folder layout, `Settings` | An empty project passing CI |
| 2 | Domain and ports; Telegram Desktop JSON import; JSONL RawStore | Data in `data/raw/` without Telethon |
| 3 | SQLAlchemy, Alembic, tables, normalization with upsert | Messages in SQLite |
| 4 | Stage runner; noise filter and enrichment with tests | Labelled messages |
| 5 | Web: "chats", "pipeline", "messages" | Visible internals |
| 6 | Thread grouping, FTS5, search page | Working search |
| 7 | Telethon connector, `login`, `sync`, worker | Automatic incremental sync |
| 8 | Docker and compose | `docker compose up` runs everything |

After step 8 — a complete service without AI. The AI stages (topic labelling, embeddings,
answers) plug in as the next stages through the same `Stage` interface. Progress is tracked
in `docs/ROADMAP.md`.
