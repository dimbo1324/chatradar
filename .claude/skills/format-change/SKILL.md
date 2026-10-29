---
name: format-change
description: Use when changing a persistent format — the JSONL record, file and folder naming, state.json, _status.json, the control-command files, config.toml or chats.toml — keeping existing data and configuration loading.
---

# Changing a Persistent Format

ChatImport's files outlive the code that wrote them. Every change keeps what is already on
the owner's disk readable.

## JSONL records

1. A new field is optional for old records and keeps `v`. Removing a field or changing its
   meaning bumps `v`, and readers accept every `v` ever written.
2. Never rewrite existing parts to migrate them; history is append-only.
3. Update `docs/architecture.md` §6 and the mapper's table-driven tests.

## File and folder naming

Part names (`YYYY-MM_NNN.jsonl`) and folder discovery by `state.json` must keep finding
existing folders. A rename rule applies to new files only.

## `state.json`, `_status.json`, control files

`state.json` is a cache rebuilt from the files: a new key has a default and recover fills
it. `_status.json` and control files are read by other processes — add fields, do not
rename them without a `v` bump on both sides.

## `config.toml` and `chats.toml`

A new setting has a safe default (an empty file still works), appears in
`config.example.toml` / `chats.example.toml` and `.ai/project/14-command-reference.md`,
and has a test. A broken library file never stops the service: it keeps the last valid
version. Renaming a key keeps the old one working for one release or is called out as a
breaking change.

## Finish

`just check`, then name any breaking change in the final report and `CHANGELOG.md`.
