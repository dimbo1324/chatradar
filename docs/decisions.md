# Decisions

Owner decisions that constrain future work, newest first. Significant architecture
decisions get an ADR in `docs/adr/`.

## Decisions

### 2026-10-29 — ChatImport on its own branch of this repository

ChatImport is developed on branch `chatimport`, cut from `main` (ChatRadar) and stripped of
ChatRadar code. It is a separate uv project named `chatimport` on Python 3.14. The two lines
are meant to become one product later (`docs/architecture.md` §15); until then this branch
neither merges into nor changes `main`. Rule modules, agents and skills on this branch
describe ChatImport only.

### 2026-10-29 — Spec decisions (spec v1.2, §18)

| # | Question | Decision |
|---|---|---|
| 1 | Sender names | stored: `sender_name` and `sender_username`, on by default |
| 2 | What is tracked | only groups and channels from the `chats.toml` library (links, @usernames, titles); no private dialogs |
| 3 | Recheck of edits | yes: daily over the last 7 days, plus on start after a long pause |
| 4 | Output path | the personal laptop's Desktop for now; changed by one command or from the tray, with data moved |
| 5 | Splitting month files | yes: month → parts `YYYY-MM_NNN.jsonl` of 20 MB; the part is the unit of accounting and trimming |

### 2026-10-19 — AI assistant rule system, Claude Code first

Rules in `.ai/` shared by every assistant; `CLAUDE.md` imports them, `AGENTS.md` and
`.codex/` are generated, `GEMINI.md` imports `AGENTS.md`. Same layout as the owner's other
repositories.

### 2026-10-19 — Publishing without pull requests

Task branch → green `just check` → `git merge --ff-only` → push, only when the owner asked
in the current task. On this line of work the target branch is `chatimport`.

### 2026-10-19 — MIT license

The repository is public under MIT.

### 2026-10-19 — English in the repository

Everything tracked by git is English; reports to the owner are in Russian.

## Open questions

- Variant A or B for the ChatRadar integration (`docs/architecture.md` §15).
- Whether to package a single `.exe` with PyInstaller.
- Telegram terms since February 2026 for any use beyond a personal archive.
