<!--
GENERATED FILE - DO NOT EDIT.
Source of truth: .ai/universal/*.md and .ai/project/*.md.
Edit a module, then run: just agents
-->

# ChatImport - working notes for Codex and other AI assistants

This file is the entry point for Codex and any tool that reads AGENTS.md. It is assembled
from the shared rule modules in `.ai/`, so every assistant follows identical rules. Later
sections override earlier ones; an explicit owner instruction in the current conversation
overrides everything. Start every task with the orientation ritual in the progress module.

---

<!-- module: .ai/universal/01-workflow.md -->

# Workflow: Git, Branches, Commits

Purpose: every task follows one predictable git cycle. No exceptions without an
explicit owner instruction in the current conversation.

## Branch discipline

- NEVER develop directly on `main`.
- Start every task from up-to-date `main`:
  `git checkout main` → `git pull --ff-only origin main` → `git checkout -b <branch>`.
- Branch name format: `type/short-task-description`
  (types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `ci`, `perf`, `security`).
- Uninformative branch names (`test`, `fix`, `work`, `final`, `new`) are forbidden.
- Merge into `main` only fast-forward (`git merge --ff-only`) and only after the
  project's full quality gate is green.
- Push to `origin/main` only when the owner explicitly asked for a publish within the
  current task. Work-in-progress branch pushes are allowed (for example, to publish
  the task checklist before starting work).
- Delete the task branch after it is merged.

## Commits

- Message format: `type: short description of what and why`.
- One commit = one logically complete unit. Do not mix a bug fix, a refactor,
  formatting, and new features in a single commit unless they are one inseparable task.
- Forbidden messages: `fix`, `update`, `wip`, `changes`, `final`, `123`.
- Keep commits attributable: include the assistant identity trailer the project already
  uses (check a recent `git log` for the convention).

## Quality gate before merge

- Run the project's checks (see the project commands module) before merging.
- If mandatory checks fail, merging into `main` is forbidden until fixed or the owner
  explicitly decides otherwise.
- Before merging, self-review the diff: changes match the task, no stray files, no
  debug leftovers, no secrets, no accidental unrelated edits.

When unsure whether an action counts as "explicitly requested": ask, or stop after the
branch commit and report instead of pushing.

---

<!-- module: .ai/universal/02-task-checklist.md -->

# Task Checklist and Definition of Done

Purpose: every task is planned before it starts and honestly accounted for after it
ends, in a file any reviewer can read without the conversation.

## task-checklist.md protocol

A file named `task-checklist.md` lives in the repository root and is always tracked by
git (never in `.gitignore`).

Before starting a task:

1. Clear or recreate `task-checklist.md` for the new task.
2. Write the main stages, checks, and expected outcomes as `[ ]` items, grouped into
   short sections (preparation / implementation / verification / completion).
   Moderate detail — stages, not keystrokes.
3. Commit the checklist BEFORE doing the main work.

After finishing the task:

4. Mark every item: `+` done, `-` not done or partially done.
5. Commit the filled checklist together with the completed work.
6. Never hide unfinished items — a `-` with an honest note is correct; a silently
   ignored item is a violation.

## Definition of Done

A task is complete only when ALL of the following hold:

- code written and matching the task, without unrequested scope;
- code formatted; lint and type checks pass;
- tests added or updated where reasonable; existing tests pass;
- project builds; no obvious errors in logs;
- no secrets, no temp files, no accidental changes in unrelated files;
- architecture and state docs updated if the task changed the system's shape;
- task checklist filled with `+`/`-`;
- final report written.

## Final report

The final report is ALWAYS the last step of a task. It states: what was done; which
files and areas changed; which checks ran and their results; dependency, API, database,
or config changes; security, performance, and compatibility risks; and — explicitly and
honestly — anything that was not done or failed.

---

<!-- module: .ai/universal/03-scope-and-code-style.md -->

# Scope Control and Code Style

Purpose: change only what the task requires, and keep code readable without decoration.

## Minimal changes

- Touch only what the current task needs. Forbidden without necessity:
  mass-reformatting other files, renaming things outside the task, changing
  architecture "while at it", rewriting working code without cause, changing UI when
  the task is not about the interface, deleting existing functionality without a
  direct requirement.
- If you discover an unrelated problem, record it separately (report it, or file it per
  the project's process) — do not mix it into the current diff.
- Do not create new documentation (README, `.md`, `.txt`) unless the task requires it
  directly. Exception: the project's designated architecture and progress documents,
  which must be kept current.

## Comments

- No comments by default. Code must be clear through structure and naming.
- A comment is allowed only when the task demands it, or when important logic stays
  non-obvious even with good naming. It explains the non-obvious "why", never restates
  the code.
- Stale, false, or misleading comments are forbidden. No doc comments that merely
  repeat a function name.

## File size

- Regular code files: keep under roughly 1000 lines; split by meaning when approaching
  the limit. Projects may set a stricter limit — the stricter limit wins.
- Application entry points (`main`-type files): under roughly 100 lines; extract
  configuration, startup, and service initialization into modules.
- Exemptions: test files, developer-tool scripts, and any files the project explicitly
  exempts.

## Frontend restraint

- No visual polish (styling, animations, decorative elements, redesign) unless the task
  is explicitly about appearance.
- When a task needs an interface, build the minimum that exercises the business logic
  correctly.
- Never change visual style, interface structure, component behavior, or user flows
  without a direct requirement.

---

<!-- module: .ai/universal/04-architecture-boundaries.md -->

# Architecture Boundaries, Workarounds, Tech Debt

Purpose: respect the project's layering; make every shortcut visible.

## Boundaries

- Follow the project's existing architecture. Forbidden: business logic in UI or
  controllers when a service layer exists; direct storage access in handlers when a
  repository layer exists; bypassing existing services and abstractions without cause;
  circular module dependencies; dumping unrelated logic into catch-all files.
- If the architecture genuinely blocks the task, do not hack around it — propose a
  proper structural change and reflect it in the architecture docs once approved.
- A doc-comment-only boundary is not enforced. Use a type only the check can construct,
  or a gate no caller can skip — and test that it accepts, not only that it rejects.

## Temporary solutions

- Workarounds are allowed only exceptionally, and every one must be recorded
  explicitly: why it exists, where it lives, its limits and risks, and when it must be
  replaced.
- Hidden workarounds are forbidden. Do not scatter uncontrolled `TODO`/`FIXME` marks;
  important debt gets a task or an entry in the project's tracking process.

## Tech debt

- Debt found during a task that cannot be fixed now is recorded explicitly (in the
  final report at minimum), never disguised as a normal solution.
- Debt touching security, data integrity, performance, or stability is priority debt —
  call it out loudly.

---

<!-- module: .ai/universal/05-security-and-secrets.md -->

# Security, Secrets, Dependencies, Portability

Purpose: nothing sensitive in the repo; every change safe within its area; the project
runs on any machine.

## Secrets — absolute ban

- NEVER put in code, git, tests, docs, or examples: passwords, API keys, tokens,
  private keys, real credentials, cookies, production `.env`, or personal user data.
- Secrets live only in `.env` (untracked), environment variables, secret managers, or
  CI/CD secrets. The repo may contain only a safe `.env.example`.
- A secret that ever reached git is compromised: rotate it; deleting the line in a new
  commit is not enough.

## Security in every task

Check within the area you touch: authorization and access rights, input validation,
injection, XSS and CSRF where applicable, unsafe redirects, file uploads, personal data
handling, public endpoints, token storage and transport, and access to admin functions.
Security is part of every task, not a future task.

## Dependencies

- No new dependency without justification: what for, can it be done without, is it
  maintained, known vulnerabilities, stack compatibility, does it duplicate an existing
  dependency, is it too heavy for the need.
- Never add a heavy library for one small function.
- After changing dependencies: update the lock file and verify the build.
- A new production dependency must be named in the final report.

## Portability

- No machine-specific values in code: local absolute paths, usernames, or anything
  environment-dependent. Such values go to configuration.
- The project must remain runnable by someone else using the project's documented tools.

---

<!-- module: .ai/universal/06-quality-and-testing.md -->

# Quality: Tests, Errors, Data, Contracts, Performance

Purpose: changes are verified, honest about failure, and safe to release.

## Tests

- Cover new or changed code where reasonable: the happy path, validation errors, edge
  cases, access rights, service and storage behavior, and regressions for fixed bugs.
- NEVER delete, disable, or weaken tests just to make a build green.
- If tests were not added, say why in the final report.
- Prefer the project's designated check runner over ad-hoc command sequences, and keep
  that runner updated when a task adds an important new part of the system.

## Errors and logging

- Handle errors explicitly. Forbidden: silently swallowed errors, empty catch blocks,
  debug logs left after the task, secrets or personal data in logs, print-style
  debugging instead of real handling.
- Logs must say where it broke, which component, what context matters, and how critical
  it is. Useful, not noisy.

## Database migrations

- Schema changes happen ONLY through migrations.
- Never edit or rename an already-applied migration; never delete migrations without a
  separate decision; never make irreversible changes without risk analysis.
- Verify each migration on a clean database, on an existing database where applicable,
  and together with the code that uses the new structure.

## Contracts

- When a task changes an API or an artifact format, update the contract and generated
  types.
- Never silently change field names, data types, response structure, error codes,
  parameter requiredness, or endpoint behavior.
- Any breaking change must be named explicitly in the final report.

## Performance and releases

- No premature optimization, but no obviously wasteful patterns: N+1 queries, heavy
  per-request computation, render loops, unpaginated large reads, redundant calls,
  blocking operations in responsive paths.
- If a change may affect performance, say so in the final report.
- Every change should be revertible; for risky changes plan the rollback before merging.
- Large new features ship behind a feature flag where the project supports them;
  unfinished functionality must not be reachable by accident; stale flags get removed
  after stabilization.

---

<!-- module: .ai/universal/07-multi-assistant.md -->

# Multi-Assistant Collaboration

Purpose: several AI assistants and humans work in this repository across separate
sessions; git is the coordination surface and the rule modules are shared.

## Coordination through git

- Before non-trivial work, check
  `git log -10 --date=iso-strict --pretty=format:"%h %cd %s"` and
  `git status --short --branch`: recent commits may be another assistant's finished
  work — not yours to redo or second-guess.
- Never rewrite history on another assistant's in-flight branch. Build on top of it or
  ask first.
- Keep commits attributable: include the assistant identity trailer the project already
  uses (see recent `git log` for the convention).

## Shared rule modules

- All assistants obey the same rules from `.ai/universal/` and `.ai/project/`. There is
  exactly one source of truth.
- `CLAUDE.md` imports the modules natively; `AGENTS.md` is GENERATED from them. Never
  hand-edit `AGENTS.md`; edit the module and run the project's sync command (see the
  project commands module).
- When a task changes shared behavior (workflow, gates, style, guardrails), change the
  module once — every assistant picks it up. Mirror-maintained per-assistant files
  (`.claude/` and `.codex/`: agents and skills) still need the same edit on both sides
  in the same task.

## Session hygiene for any model

- Re-read plans and rule files from disk instead of trusting memory of a previous
  session — files change between sessions.
- When context is shaky or the task is large, restate the task's acceptance criteria in
  the checklist before coding, and verify against files, not recollection.
- If two rules appear to conflict: the project module wins over the universal module;
  an explicit owner instruction in the current conversation wins over both. Say out
  loud which rule you chose and why.

---

<!-- module: .ai/project/10-project-map.md -->

# Project: ChatImport

ChatImport is a background service that keeps a full local text archive of the Telegram
groups and channels listed in the owner's `chats.toml` library. It runs as its own session
of the owner's account (Telethon, MTProto), backfills each chat's history once, then appends
new messages in small batches (every 5 messages or 30 seconds), rechecks the last 7 days
daily for edits and deletions, and protects free disk space by trimming the oldest parts.
Output is JSONL in a `ChatImport` folder (the Desktop by default). Product intent:
`docs/vision.md`; design: `docs/architecture.md`.

This is branch `chatimport`, a parallel line to ChatRadar on `main`. The two are meant to
become one product later (`docs/architecture.md` §15): ChatImport's JSONL folder is a
candidate raw store for ChatRadar.

**Stage: 0.0 — repository prepared, no service code yet; stage 0.1 is next.**

## Repository map

Single uv project on Python 3.14+ (`src/` layout, package `chatimport`):

- `src/chatimport/cli.py` — Typer entry point `chatimport`; thin wrappers only.
- Planned modules (spec layout, `docs/architecture.md` §12): `config.py`, `paths.py`,
  `library.py`, `app.py`, `telegram/` (`client.py`, `resolve.py`, `mapper.py`),
  `storage/` (`layout.py`, `writer.py`, `state.py`, `recover.py`), `worker.py`,
  `recheck.py`, `trim.py`, `guards/` (`disk.py`, `folders.py`), `control.py`, `tray.py`,
  `media.py`. A module joins this list when it exists.
- `config.example.toml`, `chats.example.toml` — templates; the real files live in the
  application data folder and are never tracked.
- `tests/unit`, `tests/integration`, `tests/fixtures` (anonymized data only).
- `scripts/` — stdlib-only repo tooling: `sync_agents.py`, `check_language.py`, `doctor.py`.
- `justfile`, `.pre-commit-config.yaml`, `.github/`.
- `docs/` — `vision.md`, `architecture.md`, `ROADMAP.md`, `decisions.md`.
- `.ai/`, `.claude/`, `.codex/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` — assistant rules.

## Language policy

- **Everything tracked by git is English**: code, comments, docstrings, CLI help, docs, rule
  modules, commit messages, test names, `task-checklist.md`. Owner decision 2026-10-19.
- `python scripts/check_language.py` fails on any Cyrillic character in a tracked file,
  except under `tests/fixtures/` (anonymized chat data is Russian by nature).
- The owner's original spec is Russian and lives outside the repository;
  `docs/architecture.md` is its English version and the reference inside the repository.
- Reports to the owner in chat are in Russian, short and step by step.

## Documentation policy

- `docs/vision.md` changes only when the product intent changes, by owner agreement.
- `docs/ROADMAP.md` is the plan and progress record; `docs/decisions.md` the decision log.
- The no-new-docs exception (`03-scope-and-code-style.md`) covers `README.md`, `docs/` and
  `CHANGELOG.md`.

## Product guardrails

- Only chats listed and enabled in `chats.toml` are read or stored; private dialogs, bots
  and everything else are dropped at the router.
- The service never joins a chat by itself and never sends anything to Telegram.
- Data stays on the owner's disk. Sender names are personal data (Uruguay, Ley 18.331):
  any export or publication strips them.
- Telegram is read through the owner's user account with pauses and FloodWait respected;
  history backfill runs one chat at a time.
- **Stage order in `docs/ROADMAP.md` is binding.** Skipping ahead needs an owner decision
  recorded in `docs/decisions.md`.

---

<!-- module: .ai/project/11-commands.md -->

# Project Commands and Quality Gates

All commands run from the repository root (PowerShell or Git Bash on Windows, any POSIX
shell elsewhere). Toolchain: uv (it installs Python 3.14 from `.python-version`), git,
just; `python scripts/doctor.py` checks all of them read-only.

## The one gate

```bash
just check        # lint, format, pyright strict, pytest, agents sync, language
```

CI runs the same sections as separate jobs. Without `just`, run the recipe's lines from
`justfile` one by one through `uv run`.

| Recipe | Purpose |
|---|---|
| `setup` | `uv sync` + install the pre-commit hook, once per clone |
| `fmt` / `lint` | ruff format + fix / ruff check and format check |
| `typecheck` | pyright strict over `src/`, `tests/`, `scripts/` |
| `test` / `cov` | pytest / with coverage |
| `agents` / `agents-check` | regenerate / verify `AGENTS.md` and `.codex/` |
| `language` | no Cyrillic outside the allowed data paths |
| `doctor` | read-only toolchain check |
| `hooks` | every pre-commit hook over the whole repository |

**Standing duty — keep the tooling true.** A task that changes how the project is checked,
built, run or published updates `justfile`, the CI workflow and this table in the same
task. A source whose artifact is generated (`AGENTS.md`, `.codex/agents|skills`) is
committed together with the regenerated artifact.

## Main branch (strict, owner instruction 2026-10-29)

**In this repository `chatimport` IS the main branch.** Everywhere a rule, skill, agent or
habit says `main`, read `chatimport`: branch from it, merge into it, compare against it,
push it. Never check out, modify, merge into, rebase onto or push `main` — it holds the
unrelated ChatRadar project and is off limits. If a command or document names `main`,
substitute `chatimport` and do not ask.

## Publishing

- No pull requests (owner workflow shared with the owner's other repositories).
- **This line of work lives on branch `chatimport`, not `main`.** Task branches start from
  `chatimport` (`type/short-description`) and merge back into it with
  `git merge --ff-only` after a green `just check`; then `git push origin chatimport`.
  `main` (ChatRadar) is never touched from this branch; joining the two is a separate
  owner decision.
- Agents push only when the owner asked for it in the current task. Never force-push.

## Gate policy

- `just check` is green before any merge into `chatimport`. Docs- and config-only changes
  still run it: the agents-sync and language sections cover them.
- The pre-commit hook formats and checks hygiene, secrets, pyright and generated files;
  it never replaces the full gate.
- Never skip a hook (`--no-verify`) or weaken a check to get green.

---

<!-- module: .ai/project/12-domain-rules.md -->

# Domain Rules and House Style (ChatImport)

These sharpen the universal rules for this codebase. Stricter wins.

## Python code

- Python 3.14+, full type hints, pyright strict is a gate. A `# type: ignore` or
  `# pyright: ignore` names its rule; a `# noqa` names its code and says why.
- Ruff rules in `pyproject.toml` are binding; `T20` bans `print`, `DTZ` bans naive datetimes.
- A module past roughly 500 lines is split by meaning. `cli.py` and `tray.py` hold argument
  parsing, menus and wiring only.
- Dependencies only through `uv add` / `uv add --dev`; `uv.lock` is committed. Only free
  open-source dependencies; a new one is added with the code that first uses it.

## Boundaries

- `telegram/mapper.py`, the storage layout and `trim` are pure or file-only: no Telethon
  client, no tray, no CLI imports. This keeps them portable into ChatRadar later.
- Telethon is touched only in `telegram/`. Everything else receives plain records.
- Collaborators come in through constructors (Telegram client, `disk_usage`, clock), so
  every component is testable without network and without a real disk.

## Data rules

- **One writer.** Only the service process writes into the `ChatImport` folder, and inside
  it only the chat's worker (or the trimmer holding that chat's lock). CLI and tray send
  commands through the control folder; they never write data files.
- Records are JSONL, one object per line, schema field `v`. Adding a field keeps `v`;
  removing or changing meaning bumps it. History is append-only: edits and deletions are
  new `edit`/`delete` records, never rewrites.
- Files are `YYYY-MM_NNN.jsonl` (UTC month, part number); a part is the unit of storage,
  accounting and trimming. Lines inside a part ascend by `msg_id`.
- At-least-once intake plus deduplication by `msg_id` (`last_id` in `state.json`): no
  duplicates and no gaps after a crash or restart.
- `state.json` is a cache; the JSONL files are the truth. It is written atomically
  (temp file, `fsync`, `os.replace`) and rebuilt from the files when missing or broken.
- Data files are never held open between writes (Windows must be able to delete a folder).
- Trimming removes oldest first, never selectively, and raises `floor_id`; the service
  never backfills below `floor_id` on its own.
- All datetimes are timezone-aware UTC, written as ISO 8601 with `Z`.

## Telegram and privacy

- A `*.session` file is full access to an account: it lives in the application data folder,
  is never read into a transcript, logged, committed or copied.
- `api_id`/`api_hash` live only in the real `config.toml`; the repository holds
  `config.example.toml`.
- Respect FloodWait, pause between requests and chats, backfill one chat at a time; do not
  shorten pauses for speed.
- Logs carry chat ids, message ids and counts, never message text or sender names.

## Tests

- Telegram is never called in tests: a fake client (`tests/fakes.py`) replays history and
  events from fixtures.
- Unit tests need no network and touch only `tmp_path`: the autouse fixture in
  `tests/conftest.py` isolates `CHATIMPORT_*` variables and the working directory.
- Mapper, chunking, recover and trim are table-driven; size thresholds are shrunk in tests
  (for example 1 KB parts) instead of writing large files.
- Fixtures in `tests/fixtures/` are anonymized: no real names, usernames or phone numbers.
  Real exports may be studied only locally and only as aggregates.

## Assistant workspaces

- `.claude/agents` and `.claude/skills` are the source; `.codex/agents|skills` are generated
  from them by `just agents`. Never edit `.codex/agents|skills` or `AGENTS.md` by hand.
- `.claude/settings.json` allowlists routine read and verification commands and denies
  destructive git operations and reading secrets. Extend the allowlist rather than routing
  around it; never remove a deny entry without owner approval.

---

<!-- module: .ai/project/13-progress-tracking.md -->

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
| Work consciously deferred, to come back to | `docs/backlog.md` |
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
- Work you chose not to do or could not finish → `docs/backlog.md`, with the reason; never
  only the chat. Shipped items move to `CHANGELOG.md`.
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

---

<!-- module index: extended -->

# Modules loaded on demand

These rules bind exactly like the inlined ones; only their full text lives
outside this file, to stay within the instruction budget. Read the file itself
when a task touches it — that is an obligation, not a suggestion.

## Rules Evolution: Keeping the Instructions Current

File: `.ai/universal/08-rules-evolution.md`

Never weaken a rule to make a task easier — propose changes instead; autonomous edits may only clarify or correct, never loosen; every change needs a changelog entry and a regenerated entry point.

## Time and Timestamps: Never Take a Date Without Its Moment

File: `.ai/universal/09-time-and-timestamps.md`

Read and report every date at full precision — hours, minutes, seconds, zone. For git use `--date=iso-strict` (`git log --pretty=format:"%h %cd %s"`); `--oneline`, `--date=short` and "2 days ago" never answer *when*.

## Command Reference and Platform Notes

File: `.ai/project/14-command-reference.md`

Lookup material — the planned `chatimport` commands, where configuration and data live, CI jobs and the Windows notes (UTF-8 consoles, `pythonw` autostart, files closed between writes, `os.replace` within one volume); the always-apply policies live in `11-commands.md`.
