# Task: prepare branch `chatimport` for the ChatImport service

Owner instruction of 2026-10-29: create a parallel branch `chatimport` from `main`, remove
everything ChatRadar-specific, and prepare the repository for the stack and tasks of the
ChatImport spec v1.2 (local reactive export of Telegram groups and channels to chunked JSONL).
The branch stays separate from `main`; the two products are meant to merge later.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Spec read in full; branch `chatimport` created from `main`
- Old branch `feat/chatimport` deleted — not done: `git branch -D` is on the deny list in
  `.claude/settings.json`; the owner deletes it by hand
+ This checklist committed before the main work

## 2. Implementation

+ ChatRadar code, tests, migrations, Docker, web panel, synthetic data and docs removed
+ `pyproject.toml` for `chatimport`: Python 3.14, Telethon, platformdirs, filelock, Typer;
  dev tools; `uv.lock` regenerated
+ Package skeleton `src/chatimport/` with a Typer entry point and a smoke test
+ `config.example.toml`, `chats.example.toml`; `.gitignore` and the secrets hook cover
  `config.toml`, `chats.toml`, `*.session`, `ChatImport/`
+ Tooling adapted: `justfile`, CI, CodeQL, Dependabot, pre-commit, `scripts/`
+ Rule modules, agents and skills rewritten for ChatImport; `AGENTS.md` and `.codex/`
  regenerated; `.ai/CHANGELOG.md` entry
+ Docs: README, CONTRIBUTING, SECURITY, CHANGELOG, `docs/vision.md`,
  `docs/architecture.md` (English version of the spec), `docs/ROADMAP.md`, `docs/decisions.md`

## 3. Verification

+ Project `.venv` rebuilt on Python 3.14 (`uv sync`), pre-commit hook reinstalled
+ `just check`: ruff, format, pyright strict (0 errors), agents sync, language green;
  pytest 13 passed
- `just test` exits 1 after the tests pass: pytest cannot clean up a stale
  `%TEMP%\pytest-of-dimbo1324\pytest-current` link (dated 2026-10-26, access denied even
  to `rmdir`). A machine problem, not the code: the owner removes it from an elevated shell;
  with `--basetemp` elsewhere the same 13 tests pass
+ `uv run chatimport --version` prints `0.0.1`

## 4. Completion

+ Checklist marked; work committed on `chatimport`; nothing pushed, `main` untouched
- `.claude/settings.json` still lists ChatRadar-only allow entries (recorded in
  `docs/backlog.md`; editing it needs owner approval)
