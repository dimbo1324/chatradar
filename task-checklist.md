# Task: fast substring search over the archive

Owner request of 2026-11-02: search every message for a word, as fast as Ctrl+F in a browser
(substring, any language, results while typing), shown stylishly in the desktop window.
Owner instruction for this task: write the business logic and the tests in full, but do NOT
run the tests and do NOT touch documentation.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Orientation, design agreed with the owner (SQLite FTS5 trigram index, derived cache,
  read-only access for CLI and window)
+ Contract written: `src/chatimport/search_types.py`
+ This checklist committed before the work

## 2. Backend (agent 1)

[ ] `search_index.py`: schema, indexing, search (trigram, short-query scan), context, chats,
    status, read-only opener
[ ] Incremental, crash-safe indexer in the service (backfill of the existing archive,
    new messages, edits, deletions, trim); config `[search]`; status block
[ ] CLI `chatimport search`
[ ] Tests written (not run)

## 3. Desktop page (agent 2)

[ ] Search page: type-ahead, lazy results, highlight, filters, counter, index progress
[ ] Ctrl+F from any page, navigation entry, context panel, Telegram link
[ ] Tests written (not run)

## 4. Completion

[ ] Merge, lint, types, language check (tests deliberately not run per owner)
[ ] Final report
