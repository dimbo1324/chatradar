## What and why

<!-- In short: the problem solved and the roadmap stage (docs/ROADMAP.md). -->

## How it was verified

- [ ] `just check` (ruff, pyright strict, pytest, agents sync, language) passes locally
- [ ] Mapper, writer, recover and trim changes are covered by table-driven tests
- [ ] A record or `state.json` format change keeps existing files readable

## Data safety checklist

- [ ] No secrets, `*.session`, `config.toml`, `chats.toml` or exported chats
- [ ] Fixtures contain anonymized messages only
- [ ] Nothing leaves the owner's machine
