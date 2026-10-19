# Task: learning lexicon (measure, data, mining, human review) and a redesigned panel

Owner instruction of 2026-10-19: implement points 1–4 of the lexicon plan (evaluation, the
dictionary as data, candidate mining, human decisions) and make the frontend more stylish,
responsive, with icons and fonts; record what is not done to come back to it. Synthetic data
only.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Owner approvals recorded: write path from the panel (ADR-0004), downloading the Inter font
  (OFL, `@fontsource-variable/inter` 5.2.8 via jsDelivr; three woff2 files, ~150 KB, license
  kept beside them)
+ Contracts committed first (models, ports, tables, migration 0002, `FeedbackServices`,
  settings, API docs, ADR-0003/0004, `docs/backlog.md`)
- This checklist was written at the end, not committed before the work (the plan lived in the
  chat and in the task list)

## 2. Implementation (four parallel packages, merged without conflicts)

+ A lexicon core: `Lexicon` from a snapshot, rules on data, `process` reprocesses a stage whose
  applied revision is behind, `SqlLexiconRepository`/`SqlLabelRepository`, seeding, container,
  `chatradar lexicon ...`
+ B mining and evaluation: log-odds candidate mining with occurrence/chat/author thresholds and
  privacy guards, dormancy, `chatradar mine`, `chatradar eval`, generator ground truth, the
  regression gate `tests/integration/test_eval.py`
+ C web API: endpoints of `docs/api.md`, single-message lookup, write guard (header + Origin)
+ F frontend: design system, themes, Inter, 31 drawn icons, responsive layout, new Lexicon and
  Quality pages, labeling buttons
+ Integration by the lead: CLI registration, `runtime.feedback` in the app, `.woff2` MIME type,
  `just eval`, docs

## 3. Verification

+ `just check` and `just hooks` green (777 tests)
+ Real adapters end to end on the four synthetic chats: import → eval → mine (47 candidates)
  → accept in the panel through the real API → revision 2, `pending apply` → `process`
  reprocessed 1 674 messages and marked both stages → labels from the Review page → Quality
  page numbers consistent with the labels; guard refuses a POST without the header and with a
  foreign Origin (403), unknown message → 404
+ Defect found and fixed in integration: mining proposed phrases that already exist in the
  lexicon under another language (regression test added)
- Not verified: the new pages with a long-running worker; Postgres; 768 px light, 1280 px dark
  and 375 px dark layouts; AA contrast by measurement

## 4. Deferred (all in `docs/backlog.md`)

- Stemming, per-chat weights, topic terms, incremental mining, AI proposer and judge,
  embeddings, worker wake-up on a decision, metrics history, authentication, filter gaps found
  by the evaluation (spam without link, duplicate rule), weak single-token candidates, panel
  polish items

## 5. Completion

+ Docs: README, CHANGELOG, ROADMAP, project rules (map, domain rules, commands, progress),
  rules changelog, decisions
- Merge into `main` and push: not done (not requested in this task yet)
