---
# GENERATED from .claude/skills/schema-change/SKILL.md by just agents - do not edit.
name: schema-change
description: Use when changing the database schema, the raw JSONL record format or a Settings field — Alembic migration, rebuild path, compatibility of existing data and configuration.
---

# Changing a Data Format

ChatRadar has three persistent formats: raw JSONL in `data/raw/`, the derived database,
and the `CHATRADAR_*` configuration. Each change keeps existing data loading.

## Database

1. Change the tables in `src/chatradar/storage/db/`.
2. `just revision "short description"`; review the generated file — autogenerate misses
   renames and FTS virtual tables, write those by hand.
3. Never edit an applied migration; add a new one.
4. Verify on a clean database:

   ```bash
   CHATRADAR_DATA_DIR=<temp dir> uv run alembic upgrade head
   ```

   and, when data exists, that `chatradar rebuild` produces the same result.

## Raw JSONL

The raw format is append-only and versioned by its fields. Readers accept every format
ever written; never rewrite old files. A new field is optional for old records.

## Settings

A new field has a safe default, appears in `.env.example` and in
`.ai/project/14-command-reference.md`, and has a test in `tests/unit/test_config.py`.
Renaming a variable keeps the old name working for one release or is called out as a
breaking change.

## Finish

`just check`, then update `docs/architecture.md` §6 if the schema shape changed, and name
any breaking change in the final report and `CHANGELOG.md`.
