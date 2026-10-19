---
# GENERATED from .claude/skills/code-review/SKILL.md by just agents - do not edit.
name: code-review
description: Use to review the current diff before finalizing a ChatRadar task — scope, boundaries, data formats, stage versions, privacy, language policy, tests and documentation drift.
---

# Reviewing Changes

Run this **before** merging and before the final report.

```bash
git status --short --branch
git diff main...HEAD
```

For an independent pass, delegate to the `chatradar-quality-reviewer` agent; for anything
touching sessions, secrets or personal data, also to `chatradar-privacy-security`.

## Mandatory checklist

1. **Scope.** No changes the task did not require.
2. **Boundaries.** Domain imports no adapter; no logic in CLI, routes or handlers;
   dialect SQL only in `storage/db/`.
3. **Data.** Migrations for schema changes; stage `version` bumped when behavior changed;
   raw data never mutated; old data still loads.
4. **Privacy.** No secrets, sessions or message text in code, fixtures or logs; nothing
   raw leaves the machine.
5. **Time.** UTC-aware datetimes only.
6. **Language.** English only outside the allowed data paths (`just language`).
7. **Tests.** Not deleted or weakened; Telegram not called; regressions covered.
8. **Documents.** Project map, architecture, roadmap status, decisions, README,
   changelogs, rule sync as needed (`just agents-check`).
9. **Leftovers.** Debug output, temp files, commented-out code.

Fix serious findings in the same task; record unrelated problems separately. If there are
no findings, say so plainly.
