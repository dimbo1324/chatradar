# Decisions

Owner decisions that constrain future work, newest first. Significant architecture
decisions get an ADR in `docs/adr/`.

## Decisions

### 2026-10-30 — Choices made during the hardening pass (agent proposal, owner to confirm)

Taken by the agents while fixing the audit findings of 2026-10-30; the owner did not decide
them explicitly. Each is in the code; reverting one is a code change.

| # | Choice | Why |
|---|---|---|
| 1 | Chat folder slugs transliterate Cyrillic to Latin and drop accents (`textnorm.transliterate`); a slug without letters falls back to `chat` and is never used to match a library name | Russian chats got the unreadable `chat_<id>`; a shared fallback could select the wrong chat |
| 2 | `export-json` writes to `<root>/_exports/<chat folder>.json` and leaves sender names and `raw` out unless `--names` | an export is the copy most likely to be shared (Ley 18.331); inside the chat folder it survived trims and mixed with service files |
| 3 | Control commands run at most once: the service claims a command file by renaming it before running it; a claim left by a crash is answered "interrupted", never re-run | a repeated destructive `trim` is worse than a lost command the user can resend |
| 4 | Text typed by a person (library names, titles, `--chat`) is compared through `textnorm.fold` (NFC, casefold, collapsed spaces); Telegram title refs are compared after NFC only, as the spec asks for an exact title | composed and decomposed accents and letter case named different chats |
| 5 | A disk-space stop of a backfill is persisted (`floor_id = oldest_done_id`, `floor_reason = "disk"`, `backfill.done = true`) and never resumed automatically; `backfill --deeper` resumes it | spec §8.2 step 5: an automatic resume would fetch and delete forever |
| 6 | Late live messages (`msg_id ≤ last_id`, not stored yet) are merged into their month instead of being dropped; beyond 20,000 queued events the worker catches up from Telegram and asks for a recheck | no silent loss, bounded memory |

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
- The six choices of 2026-10-30 above: confirm or change.
- Whether `export-json` may keep writing into `<root>/_exports/` while the service runs (it
  reads parts and writes its own file without the instance lock, a narrow exception to the
  one-writer rule in `.ai/project/12-domain-rules.md`).
