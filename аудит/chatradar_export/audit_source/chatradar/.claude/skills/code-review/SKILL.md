---
name: code-review
description: Use to review the current diff before finalizing a ChatImport task — scope, boundaries, the one-writer rule, data formats, crash safety, privacy, language policy, tests and documentation drift.
---

# Reviewing Changes

Run this **before** merging and before the final report.

```bash
git status --short --branch
git diff chatimport...HEAD
```

For an independent pass, delegate to the `chatimport-quality-reviewer` agent; for anything
touching sessions, secrets or personal data, also to `chatimport-privacy-security`.

## Mandatory checklist

1. **Scope.** No changes the task did not require.
2. **Boundaries.** Telethon only in `telegram/`; mapper, storage and trim free of client,
   CLI and tray; no logic in commands or menus.
3. **One writer.** Only the chat worker (or the trimmer under the chat lock) writes data.
4. **Data.** Record and `state.json` changes keep old files readable (`v` bumped when
   meaning changes); history appended, never rewritten; `msg_id` order inside parts.
5. **Crash safety.** Atomic writes where required; no file left open between writes;
   dedup by `last_id` keeps restarts free of duplicates.
6. **Privacy.** No secrets, sessions, real config or message text in code, fixtures or
   logs; nothing leaves the machine.
7. **Time.** UTC-aware datetimes only.
8. **Language.** English only outside the allowed data paths (`just language`).
9. **Tests.** Not deleted or weakened; Telegram not called; regressions covered.
10. **Documents.** Project map, architecture, roadmap status, decisions, README,
    changelogs, rule sync as needed (`just agents-check`).
11. **Leftovers.** Debug output, temp files, commented-out code.

Fix serious findings in the same task; record unrelated problems separately. If there are
no findings, say so plainly.
