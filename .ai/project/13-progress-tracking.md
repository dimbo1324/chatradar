# Project Progress Tracking

Purpose: any assistant, in any session, on any model, can locate exactly where the project
stands and where it is going — **from files, not from memory**. This is the primary
recovery mechanism after a lost conversation.

## Where the truth lives

| Question | File |
|---|---|
| What the product should become | `docs/vision.md` |
| How it is designed, step by step | `docs/architecture.md` |
| What is planned, in what order, what is done | `docs/ROADMAP.md` |
| Owner decisions and open questions | `docs/decisions.md` |
| Significant architecture decisions | `docs/adr/` |
| What the current or last task was | `task-checklist.md` |
| What actually happened recently | `git log -15 --date=iso-strict --pretty=format:"%h %cd %s"` |
| How the rules themselves changed | `.ai/CHANGELOG.md` |
| What users can see changed | `CHANGELOG.md` |

## Orientation ritual — at the start of EVERY task

1. `git status --short --branch` and
   `git log -15 --date=iso-strict --pretty=format:"%h %cd %s"`.
2. `docs/ROADMAP.md` — **the first step without a `**Status.**` line is next**, unless the
   owner says otherwise.
3. `task-checklist.md` — what the previous task was and whether it finished cleanly.
4. `docs/decisions.md` — whether a decision changes the plan.
5. `docs/architecture.md` — the section for the step you are about to implement.
6. Only then plan the new task.

## Update duties when finishing work

- Finished a roadmap step or a significant slice → add or refresh its `**Status.**` line in
  `docs/ROADMAP.md` (date, what shipped) and the status column of the table.
- Changed the system's shape (a module, table, command, stage, setting) → update
  `.ai/project/10-project-map.md` and, if the design moved, `docs/architecture.md`.
- Owner decision that constrains future work → `docs/decisions.md`, not only the chat.
- Significant architecture decision → a new ADR in `docs/adr/`.
- Changed a rule module, agent or skill → `.ai/CHANGELOG.md` and `just agents`.
- Changed what a user installs, configures or sees → `README.md` and `CHANGELOG.md`.

## Drift guard

If the plan, the state documents and the code disagree: **the code is the fact, the plan is
the intent**. Reconcile them in the same task or report the mismatch explicitly. Stale
documentation is worse than no documentation.

## Unfinished-task rule

If `task-checklist.md` still holds open `[ ]` items from a previous session, resolve them
first: finish them, or mark them `-` with an honest note.
