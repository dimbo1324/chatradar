# Task: API key guide, first-run wizard, combined archive file

Owner request of 2026-11-02: (0) a step-by-step guide for getting Telegram `api_id` and
`api_hash`, with validation of pasted values and a README section; (1) a five-step first-run
wizard (keys with the guide, Telegram sign-in, chat links, data folder, run mode); (2) one
combined file with every chat's messages sorted by time, rebuilt in the background and on
demand. Per-chat files stay as they are.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Orientation (git status and log, ROADMAP, decisions, architecture)
+ Decisions recorded in `docs/decisions.md` (combined file is rebuilt from the parts, never
  appended to; names stripped by default)
[ ] This checklist committed before the work

## 2. Key guide (stage 0.8a)

[ ] Guide dialog with numbered steps, schemes, link to my.telegram.org, ERROR hints
[ ] `api_id` / `api_hash` validation on paste (Settings and wizard)
[ ] README section with the same steps
[ ] Tests at full coverage

## 3. First-run wizard (stage 0.8b)

[ ] Five steps: keys, sign-in, chats, data folder, run mode
[ ] Shown when the service needs setup; reachable again from Settings
[ ] Default run mode: autostart and background; default folder Desktop\ChatImport
[ ] Tests at full coverage

## 4. Combined file (stage 0.8c)

[ ] Backend: merge parts of all chats by time into one atomic file (`_exports/`)
[ ] `[merged]` config (enabled, format, interval, names), service timer, rebuild only when
    something changed, command `export_all`, CLI `export-all`
[ ] Data page: card with status, "Build now", settings toggle
[ ] Tests at full coverage

## 5. Verification and completion

[ ] `just check` equivalent green: ruff, pyright, language, agents sync, full pytest
[ ] Docs: ROADMAP, architecture, project map, command reference, README, CHANGELOG
[ ] Final report
