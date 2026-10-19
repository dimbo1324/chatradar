## What and why

<!-- In short: the problem solved and the roadmap step (docs/ROADMAP.md). -->

## How it was verified

- [ ] `just check` (ruff, pyright strict, pytest, agents sync, language) passes locally
- [ ] New rules and mappers are covered by table-driven tests
- [ ] A migration is added and applies on an empty SQLite (if the schema changes)

## Data safety checklist

- [ ] No secrets, `.env`, `*.session` or chat exports
- [ ] Fixtures contain anonymized messages only
- [ ] No raw messages leave the machine — only summaries and links
