---
# GENERATED from .claude/skills/step-episode/SKILL.md by just agents - do not edit.
name: step-episode
description: Use to plan and execute one ROADMAP stage end to end — orientation, scoping, checklist, branch, implementation, verification, state documents and the final report.
---

# Executing a Roadmap Stage

One `docs/ROADMAP.md` stage is one task. Do not merge two stages into one task, and do not
skip the order without an owner decision recorded in `docs/decisions.md`.

## 1. Orientation (mandatory, no skipping)

```bash
git status --short --branch
git log -15 --date=iso-strict --pretty=format:"%h %cd %s"
```

Then read, in order: `docs/ROADMAP.md` (the first stage without a `**Status.**` line is
yours), `task-checklist.md`, `docs/decisions.md`, and the matching sections of
`docs/architecture.md`. Product intent: `docs/vision.md`.

If `task-checklist.md` still has open `[ ]` items from a previous session, resolve them
first.

## 2. Planning

For a large or unfamiliar stage, delegate to the `chatimport-step-planner` subagent.
Define boundaries, the owning module for each piece, every data format touched, risks and
acceptance criteria. Fill `task-checklist.md` with `[ ]` items grouped into preparation /
implementation / verification / completion, and **commit it before writing code**.

## 3. Branch

This line of work lives on `chatimport`, not `main`:

```bash
git checkout chatimport
git pull --ff-only origin chatimport
git checkout -b feat/stage-0-N-short-description
```

## 4. Implementation

Delegate where it helps: `chatimport-telegram`, `chatimport-storage`,
`chatimport-interfaces`, `chatimport-platform`. Format changes follow `format-change`.

## 5. Verification

```bash
just check
```

Exercise the acceptance criteria end to end where possible (`chatimport` commands with
`CHATIMPORT_ROOT` pointing at a temporary folder and the fake Telegram client). A live
Telegram run is the owner's step unless they ask otherwise. Run the `code-review` skill or
the `chatimport-quality-reviewer` subagent before finalizing.

## 6. Completion

- Mark checklist items `+`/`-` honestly.
- Add the `**Status.**` line under the stage in `docs/ROADMAP.md` and update its table row.
- Update `.ai/project/10-project-map.md`, `.ai/project/14-command-reference.md`,
  `README.md` and `CHANGELOG.md` where the change is visible there.
- If the stage exposed stale or missing rules, apply the `rules-evolution` skill.
- Fast-forward merge into `chatimport` only with a green gate; push only when the owner
  asked.
- Write the final report in Russian: what was done, what was verified, what was not done.
