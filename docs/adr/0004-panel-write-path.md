# ADR-0004. A narrow write path from the panel

- Status: accepted (refines the rule "only the worker writes to SQLite")
- Date: 2026-10-19

## Context

The panel was read-only. Human review of lexicon candidates and labels for the evaluation
set needs it to record two kinds of facts. Routing them through the worker would need a
queue the project does not have yet.

## Decision

- The panel may write **only** term decisions (`lexicon_terms` status and decision fields,
  `lexicon_state` revision) and message labels (`message_labels`), through
  `FeedbackServices` and the `LexiconRepository`/`LabelRepository` ports. Messages,
  threads, the search index and sync state stay worker-only.
- SQLite in WAL mode serializes writers (`busy_timeout` is set), so a rare panel write next
  to the worker is safe. Postgres has no such limit.
- The panel never runs the pipeline. A decision moves the lexicon revision; the pipeline
  applies it at the next `process` or worker cycle, and the panel says so.
- Write endpoints are protected against cross-site requests: they require the header
  `X-Requested-With: chatradar` (browsers do not let a foreign page send it without a CORS
  preflight, and CORS is not enabled) and, when an `Origin` header is present, it must match
  the request's host. The panel binds to 127.0.0.1 by default.

## Consequences

- The data rule becomes: "the worker writes everything except term decisions and labels".
- Any new panel write needs an ADR amendment first.
- No authentication yet: the panel is a local tool. Before it is exposed beyond localhost,
  authentication is a prerequisite (backlog).
