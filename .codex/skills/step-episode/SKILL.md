---
# GENERATED from .claude/skills/step-episode/SKILL.md by just agents - do not edit.
name: step-episode
description: Use to plan and execute one ROADMAP step end to end — orientation, scoping, checklist, branch, implementation, verification, state documents and the final report.
---

# Executing a Roadmap Step

One `docs/ROADMAP.md` step is one task. Do not merge two steps into one task, and do not
skip the order without an owner decision recorded in `docs/decisions.md`.

## 1. Orientation (mandatory, no skipping)

```bash
git status --short --branch
git log -15 --date=iso-strict --pretty=format:"%h %cd %s"
```

Then read, in order: `docs/ROADMAP.md` (the first step without a `**Status.**` line is
yours), `task-checklist.md`, `docs/decisions.md`, and the matching section of
`docs/architecture.md`. Product intent: `docs/vision.md`.

If `task-checklist.md` still has open `[ ]` items from a previous session, resolve them
first.

## 2. Planning

For a large or unfamiliar step, delegate to the `chatradar-step-planner` subagent.
Define boundaries, the owning package for each piece, every data format touched, risks and
acceptance criteria. Fill `task-checklist.md` with `[ ]` items grouped into preparation /
implementation / verification / completion, and **commit it before writing code**.

## 3. Branch

```bash
git checkout main
git pull --ff-only origin main
git checkout -b feat/step-N-short-description
```

## 4. Implementation

Delegate where it helps: `chatradar-connectors`, `chatradar-pipeline`, `chatradar-storage`,
`chatradar-interfaces`, `chatradar-platform`. Stage changes follow `pipeline-stage-change`;
schema changes follow `schema-change`.

## 5. Verification

```bash
just check
```

Exercise the acceptance criteria end to end where possible (`chatradar` commands on a
temporary `CHATRADAR_DATA_DIR`, the web panel through `.claude/launch.json`). Run the
`code-review` skill or the `chatradar-quality-reviewer` subagent before finalizing.

## 6. Completion

- Mark checklist items `+`/`-` honestly.
- Add the `**Status.**` line under the step in `docs/ROADMAP.md` and update its table row.
- Update `.ai/project/10-project-map.md`, `README.md` and `CHANGELOG.md` where the change is
  visible there.
- If the step exposed stale or missing rules, apply the `rules-evolution` skill.
- Fast-forward merge into `main` only with a green gate; push only when the owner asked.
- Write the final report in Russian: what was done, what was verified, what was not done.
