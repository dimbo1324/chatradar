# ADR-0001. Modular monolith with ports and adapters

- Status: accepted
- Date: 2026-10-19

## Context

The project starts as an MVP for one user but must grow into a platform with several
messengers, a web dashboard, a bot and an API. The team is one or two people. The
bottlenecks are Telegram API limits and LLM cost, not Python performance.

## Decision

- One application (a modular monolith), the `chatradar` package.
- At the center: the domain model (`Message`, `Thread`, `Chat`) and `Protocol` ports
  (`Connector`, `RawStore`, `MessageRepository`, `SearchIndex`, `Stage`).
- Telethon, SQLite/Postgres, FastAPI and aiogram are adapters. `domain/` never imports them.
- The boundary between modules is a data format (JSONL, database tables), not Python objects.
- Raw data is immutable and stored separately (`data/raw/*.jsonl`); the database is derived
  and rebuilt by `rebuild`.
- The pipeline consists of idempotent, versioned stages.

## Consequences

- A new messenger is a new connector; the core does not change.
- SQLite → Postgres is a new repository adapter and a different `DATABASE_URL`.
- Any stage can move to a separate service or be rewritten in another language.
- Cost: import discipline (domain → nothing; adapters → domain), checked in review;
  `import-linter` can enforce it in CI later.
- Deliberately not used at the start: Celery, Redis, Kafka, React, microservices.
