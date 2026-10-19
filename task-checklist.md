# Task: AI-assistant setup, English-only repository, toolchain check

Owner instruction of 2026-10-19: study the AI-assistant setup of `daily-quest`, `codepack`
and `CogniBoiler` and build the same in ChatRadar so every assistant (Claude Code first)
knows the project's purpose, currency and state and can cooperate; translate every text in
the repository to English; verify that everything works and install the missing toolchain
on this machine; commit and push.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Study the rule systems of the three reference repositories (`daily-quest` is the newest
  and the template; `universal/` modules are identical in all three)
+ Task branch `chore/ai-assistant-setup`
- This checklist was written during the work, not committed before it (the rule system
  did not exist yet when the task started)

## 2. Implementation

+ `.ai/universal` (verbatim) and `.ai/project/10–14` for ChatRadar
+ `CLAUDE.md`, generated `AGENTS.md` (26.7 of 30 KiB), `GEMINI.md`
+ `.claude/` settings, launch, 9 agents, 7 skills; generated `.codex/` mirror
+ `scripts/sync_agents.py`, `scripts/check_language.py`, `scripts/doctor.py` with tests
+ State documents: `docs/ROADMAP.md`, `docs/decisions.md`, this checklist
+ Gate wiring: `justfile`, pre-commit, CI (`assistants` job)
+ Translate code, comments, docs and configs to English; RUF001–003 re-enabled
+ Fix the Docker build failure from CI (missing `LICENSE` in the build context)
+ The deny rule `Read(./.env.*)` also hid `.env.example`; narrowed with owner approval

## 3. Verification

+ Toolchain: `just` 1.59.0 installed; `just doctor` reports "ready to develop"
- GitHub CLI not installed: the MSI installer was cancelled (exit 1602, elevation prompt);
  optional, `winget install GitHub.cli` when convenient
- Docker daemon not running (Docker Desktop is started by the owner); the image is
  verified by the CI Docker job
+ `just check` green (25 tests); `just hooks` green
+ Alembic on an empty SQLite, CLI `--version` and stub exit code, web panel `/healthz`
  through `.claude/launch.json`
- CI after push: cannot be verified before the push; reported in the final report

## 4. Completion

+ Fast-forward merge into `main` and push
+ Final report to the owner
