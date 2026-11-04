# Rule Changes Changelog

History of changes to the AI assistant rule system (`.ai/`, `CLAUDE.md`, `AGENTS.md`,
`GEMINI.md`, `.claude/`, `.codex/`). Every rule change gets an entry here — see
`universal/08-rules-evolution.md` for the protocol.

Format: date, what changed, why, who decided. Newest first.

## 2026-10-31 — Application icon in the lookup table

**What changed.** `project/14-command-reference.md`: one row in "Where things live" for the
bundled icon (`src/chatimport/assets/icon.png`, `icon.ico`).

**Why.** The owner supplied an icon and asked for it to be the project's main icon; the
tray and README use it.

**Decided by.** Owner (the icon), agent (wording), 2026-10-31.

## 2026-10-31 — Rules brought in line with the implemented service

**What changed.** `project/10-project-map.md`: stage line (0.1-0.7 implemented and
hardened) and the actual module map instead of the planned one. `project/12-domain-rules.md`:
`cli*.py`/`tray*.py`; the one-writer rule names the claimed-command protocol (at most once)
and the offline CLI under the instance lock; `StateUnreadable` is never rebuilt over; a
multi-part month is rewritten only through `storage/month_commit.py`; one backfill at a time
names `runtime.BackfillSlots`; logs never carry invite hashes; tests use the scripted gateway.
`project/14-command-reference.md`: every command listed as implemented with its real options
and its behaviour with and without a running service, log location, control-queue protocol,
pyright-on-Linux CI note, new Essence line. Agents `chatimport-interfaces`, `-storage`,
`-telegram`, `-step-planner`: ownership lists match the split modules; the tray is tested
through a fake `pystray`. No rule was loosened.

**Why.** The documents still described stage 0.0 although the service was implemented,
tested and refactored on 2026-10-29/30; the code is the fact.

**Decided by.** Owner asked for a documentation refresh; agent wording, 2026-10-31.

## 2026-10-29 — `chatimport` is the main branch

**What changed.** `project/11-commands.md`: a strict section making `chatimport` the main
branch of this repository and forbidding any work on `main` (ChatRadar).

**Why.** Owner instruction: agents must treat `chatimport` as `main` and never touch `main`.

**Decided by.** Owner, 2026-10-29.

## 2026-10-29 — Branch `chatimport`: rules rewritten for ChatImport

**What changed.** On branch `chatimport` only: every `project/` module now describes
ChatImport (map, commands, domain rules, command reference); `11-commands.md` makes
`chatimport` the base and merge target of this line of work instead of `main`, which wins
over `universal/01-workflow.md` here. Agents renamed to `chatimport-*`; `connectors`,
`pipeline`, `storage` and `interfaces` replaced by `telegram`, `storage` and `interfaces`
for this service; skills `pipeline-stage-change` and `schema-change` replaced by
`format-change`; `launch.json` removed (no web panel). Universal modules are unchanged.

**Why.** The owner started ChatImport as a separate line of work in the same repository,
to be merged with ChatRadar later; ChatRadar's rules would mislead every session here.

**Decided by.** Owner (branch and scope), agent (wording), 2026-10-29.

## 2026-10-19 — Learning lexicon in the rules

**What changed.** `project/10-project-map.md` (stage, `learning/`, lexicon and evaluation
modules, `docs/backlog.md`), `project/12-domain-rules.md` (the lexicon is data and only
proposed by statistics; terms are phrases, never people; the panel's narrow write path),
`project/13-progress-tracking.md` (deferred work goes to `docs/backlog.md`),
`project/11-commands.md` and `14-command-reference.md` (`eval`, `mine`, `lexicon`).

**Why.** ADR-0003 and ADR-0004 made those lines false or incomplete; the owner approved
the data-rule change (the panel writes decisions and labels) by asking for the feature.

**Decided by.** Owner (feature and write path), agent (wording), 2026-10-19.

## 2026-10-19 — The panel's interface is Russian

**What changed.** `project/10-project-map.md` (language policy) names the exception: the
panel's UI strings, kept in `web/static/i18n/ru.json` and the `index.html` shell, are
Russian. `.claude/agents/chatradar-interfaces.md` (and its generated Codex mirror) tells
agents to add every new string as a key, never as a literal in JavaScript.

**Why.** Owner instruction of 2026-10-19: the frontend interface in Russian. The language
policy changes only with owner approval, and this is it; the exception is limited to UI
text as data, so code, comments, docs and commits stay English.

**Decided by.** Owner, 2026-10-19 (recorded in `docs/decisions.md`).

## 2026-10-19 — Synthetic data and real exports

**What changed.** `project/12-domain-rules.md` adds the rule that real chat exports are
studied only locally and as aggregates, and that realistic test data goes through
`scripts/generate_synthetic.py`. `project/10-project-map.md` and `project/11-commands.md`
list the generator, its fixtures and the `synthetic`, `synthetic-check` and `demo` recipes;
`just check` now includes `synthetic-check`.

**Why.** The owner asked for synthetic data based on their real chats; the privacy
constraint must survive into later sessions. A new constraint the owner's request
implies and a new gate section, both additions, not loosenings.

**Decided by.** Owner (task), agent (wording), 2026-10-19.

## 2026-10-19 — Project modules follow the built MVP

**What changed.** `project/10-project-map.md` states the stage (MVP steps 1–8 built, live
Telegram login pending) and lists the services (`container.py` as the composition root,
ingest, sync, process, rebuild, worker) and the pipeline modules and lexicons.
`project/14-command-reference.md` (extended tier) describes the working CLI instead of
step numbers and exit code 2.

**Why.** The MVP made those lines false. Factual corrections, which
`universal/08-rules-evolution.md` allows without approval.

**Decided by.** Agent, as part of the owner-requested MVP of 2026-10-19.

## 2026-10-19 — Rules follow the MVP contracts and the static frontend

**What changed.** `project/10-project-map.md` describes the contract modules
(`domain/text.py`, the full port list, `services/normalize.py`, `services/queries.py`) and
the web package as a JSON API plus a static plain-JavaScript panel.
`.claude/agents/chatradar-interfaces.md` (and its generated Codex mirror) drops Jinja2 and
HTMX, points at `docs/api.md` and ADR-0002, and requires `textContent` for message text.

**Why.** The owner decided the frontend is plain HTML, CSS and JavaScript (ADR-0002) and
the MVP contracts were written; the old lines were factually false. Corrections, which
`universal/08-rules-evolution.md` allows without approval.

**Decided by.** Owner (frontend), agent (factual update), 2026-10-19.

## 2026-10-19 — The rule system arrives

**What changed.** ChatRadar gains the assistant rule system the owner runs in `daily-quest`,
`codepack` and `CogniBoiler`:

- `.ai/universal/01–09` copied verbatim from `daily-quest` (identical in all three).
- `.ai/project/10–14` written for this project: repository map with language and product
  guardrails, commands and gate policy (`just check`), domain rules (hexagonal boundaries,
  immutable raw data, versioned idempotent stages, UTC datetimes, Telegram session and
  privacy rules), progress tracking, and a command reference marked `tier: extended`.
- `CLAUDE.md` imports every module; `AGENTS.md`, `.codex/agents` and `.codex/skills` are
  generated by `scripts/sync_agents.py` (a Python port of `daily-quest`'s
  `sync-agents.mjs`: `.claude/` is the source, the 30 KiB budget and tier rules are kept).
  `GEMINI.md` imports `AGENTS.md`.
- `.claude/agents` and `.claude/skills` carry the project subagents and workflows;
  `.claude/settings.json` the allow and deny lists. The deny list blocks reading `.env`,
  `.env.local`, `.env.*.local`, `.env.prod*` and session files but leaves `.env.example`
  readable (narrowed from `.env.*` with owner approval, 2026-10-19).
- `scripts/check_language.py` enforces the English-only policy, with an allowlist for
  Russian and Spanish data (fixtures, lexicons).
- State documents: `docs/ROADMAP.md`, `docs/decisions.md`, `task-checklist.md`.

**Why.** The owner asked for assistants to always understand the project's purpose,
currency and state and to cooperate, by analogy with the other repositories; Claude Code
is the priority assistant. Everything in the repository is English (owner instruction,
2026-10-19).

**Adapted, not copied.** The gate is `just check` instead of `npm run check` or a script
orchestrator; the language check allows Cyrillic in data files, because noise lexicons and
anonymized fixtures are Russian and Spanish by nature.

**Decided by.** Owner, 2026-10-19 (recorded in `docs/decisions.md`).
