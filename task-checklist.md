# Task: bring the ChatImport documentation in line with the code

Owner request of 2026-10-31: the documents still described stage 0.0 although the service
(spec stages 0.1–0.7) was implemented on 2026-10-29 and audited and refactored on
2026-10-30. Update every state, rule and user document from the code; no code changes under
`src/` or `tests/`; the lead reviews and commits.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Orientation: git status and log with full timestamps, ROADMAP, checklist, decisions,
  architecture
+ Commit messages of 2026-10-29/30 and the audit reports and fix brief read
+ Code read for every claim (modules, CLI options, control protocol, storage, worker,
  guards, media, logging)
- This checklist committed before the work — not done: the lead commits this task as a
  whole (instruction: do not commit)

## 2. Implementation

+ `.ai/project/10-project-map.md`: stage line and the actual module map
+ `.ai/project/12-domain-rules.md`: false or stale statements corrected (no rule loosened)
+ `.ai/project/14-command-reference.md`: every command implemented, logs, control queue,
  CI note, new Essence line
+ `.ai/project/11-commands.md` reviewed: nothing false found, left unchanged
+ Agents `chatimport-interfaces`, `-storage`, `-telegram`, `-step-planner`: ownership lists
+ `.ai/CHANGELOG.md` entry; `AGENTS.md` and `.codex/` regenerated
+ `docs/ROADMAP.md`: status lines for 0.1–0.7 and the hardening pass, the live check named
  as the next step, 1.0 open
+ `docs/architecture.md`: §4–§12 and §14–§15 updated to the code; §12 actual module layout
+ `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`
+ `docs/decisions.md`: the implicit choices of 2026-10-30 as agent proposals
+ `docs/backlog.md`: deferred findings with reasons; solved items removed
+ `.gitignore`: `/_unrouted_deletes.jsonl` and `/_exports/`

## 3. Verification

+ `scripts/check_language.py` green
+ `scripts/sync_agents.py --check` green (AGENTS.md 29.7 of 30 KiB)
+ `ruff format --check .` green
+ pre-commit hooks on the changed files green
+ Tests re-run for the coverage claim: 3155 passed, 3 skipped, 100 % line and branch
  (Windows)
- Live behaviour against Telegram not verified — out of scope; the owner's next step

## 4. Completion

+ Checklist marked
- Nothing committed or pushed — by instruction; the lead reviews and commits
