# JSON API

The web panel is a static single-page app (plain HTML, CSS and JavaScript modules, no build
step) served by FastAPI, which also serves this JSON API. The panel only reads; the worker
is the only writer. Response bodies are the pydantic models in
`src/chatradar/domain/models.py`, serialized by FastAPI (datetimes as ISO 8601 with `Z`/offset).

All endpoints bind to 127.0.0.1 by default. Errors use FastAPI's `{"detail": ...}` shape:
404 for an unknown thread, 422 for invalid parameters.

| Method and path | Query parameters | Response |
|---|---|---|
| `GET /healthz` | — | `{"status": "ok", "version": str}` |
| `GET /api/chats` | — | `list[ChatSummary]` |
| `GET /api/pipeline` | — | `PipelineStats` |
| `GET /api/messages` | `source`, `chat_id`, `date_from`, `date_to`, `lang`, `is_noise`, `noise_reason`, `is_question`, `thread_id`, `limit` (1–500, default 50), `offset` (default 0) | `MessagePage` |
| `GET /api/threads/{thread_id}` | — | `ThreadDetail` (404 if unknown) |
| `GET /api/search` | `q` (required, may be empty → `[]`), `source`, `chat_id`, `date_from`, `date_to`, `limit` (1–100, default 20) | `list[ThreadHit]` |
| `GET /api/review` | `noise` (bool, required), `n` (1–200, default 100) | `list[StoredMessage]` — a random sample |
| `GET /api/noise-reasons` | — | `dict[str, int]` — reason → count |

`thread_id` contains a colon (`-100123:42`); clients URL-encode it in the path.

## Static files

| Path | Content |
|---|---|
| `GET /` | `src/chatradar/web/static/index.html` |
| `GET /static/...` | everything under `src/chatradar/web/static/` |

The app uses hash routing (`#/chats`, `#/pipeline`, `#/messages`, `#/threads/<id>`,
`#/search`, `#/review`), so the server never needs to know client routes.

## Application factory

`chatradar.web.app.create_app(read: ReadServices | None = None) -> FastAPI`. With `None`
the app builds the real services from `Settings` at startup
(`chatradar.services.container.build_read_services`); tests pass a `ReadServices` over
in-memory fakes.
