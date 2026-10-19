---
name: pipeline-stage-change
description: Use when adding or changing a pipeline stage or rule (normalize, noise, enrich, threads, index, later AI stages) — versioning, idempotency, table-driven tests and reprocessing.
---

# Changing a Pipeline Stage

## 1. Decide what changes

- New stage: a class satisfying `chatradar.pipeline.base.Stage` (`name`, `version`,
  `depends_on`, `process`), added to `STAGE_ORDER`, with its `<stage>_v` column (see
  `schema-change`).
- Changed behavior of an existing stage (a rule, a threshold, a lexicon entry): **bump
  that stage's `version`** in the same commit. The runner reprocesses only outdated rows.

## 2. Keep it pure and idempotent

- Rule and mapper functions take data and return data; no I/O, no clock reads (pass time
  in), no global state.
- Running a stage twice gives the same result. Noise is marked, never deleted.
- Lexicons and thresholds live in data files under `src/chatradar/resources/lexicons/` or in
  `Settings`, not inline in code; that path is allowed to contain Russian and Spanish.

## 3. Test

- Table-driven tests: one row per case, "input → expected output/reason".
- Every misclassification found by hand becomes a new row before the fix.
- Sample texts in other languages go to `tests/fixtures/` (anonymized), not into Python
  files.
- An integration test runs the stage through the runner on temporary SQLite.

## 4. Verify and record

```bash
just check
```

Record the version bump and its reason in the commit body. If the stage's shape changed,
update `docs/architecture.md` §5 and `.ai/project/10-project-map.md`.
