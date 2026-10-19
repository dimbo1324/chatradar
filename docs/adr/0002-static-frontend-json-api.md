# ADR-0002. Static frontend in plain HTML, CSS and JavaScript over a JSON API

- Status: accepted (supersedes the Jinja2 + HTMX choice in `docs/architecture.md` §7)
- Date: 2026-10-19

## Context

The architecture planned the debug panel as server-rendered Jinja2 templates with HTMX. The
owner decided the frontend is written in plain JavaScript, CSS and HTML. A future web
dashboard and the Telegram bot need a JSON API anyway.

## Decision

- FastAPI serves a JSON API under `/api` (`docs/api.md`) and static files from
  `src/chatradar/web/static/`.
- The frontend is a single-page app of native ES modules: no framework, no bundler, no
  npm dependencies, no build step. Hash routing.
- Jinja2 and HTMX are not used.

## Consequences

- The API is the contract between backend and frontend and can be built in parallel.
- The same API serves the later dashboard and integrations.
- No server-side rendering: every page needs JavaScript. Acceptable for a local debug panel.
- `jinja2` is removed from the dependencies.
