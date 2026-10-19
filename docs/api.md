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
| `GET /api/messages/{source}/{chat_id}/{msg_id}` | — | `StoredMessage` (404 if unknown) — one message, e.g. a lexicon example |
| `GET /api/threads/{thread_id}` | — | `ThreadDetail` (404 if unknown) |
| `GET /api/search` | `q` (required, may be empty → `[]`), `source`, `chat_id`, `date_from`, `date_to`, `limit` (1–100, default 20) | `list[ThreadHit]` |
| `GET /api/review` | `noise` (bool, required), `n` (1–200, default 100) | `list[StoredMessage]` — a random sample |
| `GET /api/noise-reasons` | — | `dict[str, int]` — reason → count |

`ThreadHit.snippet` is plain text with every matched word wrapped in `[[` and `]]`; the
frontend turns those into `<mark>` elements through DOM nodes, never `innerHTML`.
Thread messages are chronological; noise messages belong to no thread.

`thread_id` contains a colon (`-100123:42`); clients URL-encode it in the path.

## Learning lexicon and labels

Models: `src/chatradar/domain/lexicon.py` and `src/chatradar/domain/evaluation.py`. Background:
`docs/adr/0003-learning-lexicon.md`. Writes are allowed only here (`docs/adr/0004-panel-write-path.md`).

| Method and path | Query / body | Response |
|---|---|---|
| `GET /api/lexicon/summary` | — | `LexiconSummary` (`pending_apply` is true while a stage still runs on an older revision) |
| `GET /api/lexicon/terms` | `kind`, `status`, `lang`, `order` (`score` default, `occurrences`, `recent`), `limit` (1–500, default 100), `offset` | `TermPage` |
| `POST /api/lexicon/decision` | JSON `{kind, lang, term, decision, note?}`, `decision` is `accept`, `reject` or `reset` | the updated `LexiconTerm`; 404 for an unknown term |
| `GET /api/labels` | `limit` (1–5000, default 5000) | `list[MessageLabel]`, newest first |
| `POST /api/labels` | JSON `{source, chat_id, msg_id, is_noise, reason?, is_question?}` | the saved `MessageLabel`; 404 for an unknown message, 422 for a reason without `is_noise` or an unknown reason |
| `GET /api/quality` | — | `EvalReport` of the current filter against the human labels (`total` is 0 until something is labeled) |
| `GET /api/noise-reason-list` | — | `list[str]` — the noise reasons a label may carry |

Both POST endpoints require the header `X-Requested-With: chatradar` (403 otherwise) and, when an
`Origin` header is present, it must equal the request's own origin (403 otherwise).

`LexiconTerm.examples` holds message keys only; the panel opens them through
`GET /api/messages` filters or `#/threads/...`, never as raw text from the lexicon.

A decision only moves the lexicon revision. The pipeline applies it at the next `process` or
worker cycle; the panel shows `pending_apply` for that.

## Interface language

The panel is Russian. Its text is in `static/i18n/ru.json` (flat keys; counted nouns are
objects with the plural forms `one`, `few`, `many`, `other`). The API itself is language-neutral:
field names, enum values (`noise_reason`, `media_type`, stage names) and error `detail` texts
stay English; the panel translates enum values and explains errors by HTTP status.

## Static files

| Path | Content |
|---|---|
| `GET /` | `src/chatradar/web/static/index.html` |
| `GET /static/...` | everything under `src/chatradar/web/static/`, including `i18n/ru.json` |

The app uses hash routing (`#/chats`, `#/pipeline`, `#/messages`, `#/threads/<id>`,
`#/search`, `#/review`), so the server never needs to know client routes.

## Application factory

`chatradar.web.app.create_app(read: ReadServices | None = None) -> FastAPI`. With `None`
the app builds the real services from `Settings` at startup
(`chatradar.services.container.build_read_services`); tests pass a `ReadServices` over
in-memory fakes.
