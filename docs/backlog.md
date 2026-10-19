# Backlog: deferred work

Things that were considered and deliberately not done yet, so they are not lost. Newest
sections first. When an item ships, move it to `CHANGELOG.md`; when it is dropped, say why.

## From the learning-lexicon task (2026-10-19)

Context: `docs/adr/0003-learning-lexicon.md`, `docs/adr/0004-panel-write-path.md`.

### Learning

- **Filter gaps measured on the synthetic truth** (`chatradar eval`): spam without a link or
  a contact phrase is missed (recall 0.61 on `spam`); the `duplicate` rule flags ~100
  repeated phrase-bank replies (precision 0.04, which drags noise precision to 0.61).
  Tighten the duplicate rule (same author or a time window, a longer minimum) and widen
  spam. The regression gate is `tests/integration/test_eval.py`; raise its thresholds
  together with the fixes.
- **Weak mined candidates.** Single-token spam n-grams ("500", "al", "from") and
  overlapping n-grams ("anyone know" and "anyone know how") appear in the queue; require two
  tokens or a higher score for unigrams, and collapse overlaps.
- **Cautious scores on small corpora.** A whole-message `gratitude` candidate passes the
  default z-score 2.5 only with 18+ occurrences; revisit with real data.
- **Language detection** is 0.81 accurate on the synthetic truth (short texts are
  `unknown` by design); evaluate and improve per language.
- **Postgres is untested** for the new repositories (insert-or-ignore is written for both
  dialects, tests run on SQLite).
- Seeding new ACTIVE terms into an existing lexicon moves the revision (so stages
  reprocess once); documented behavior, not a bug.
- `chatradar lexicon list|stats` open the runtime (migrations and seed) on every call.
- **Lemmatization or stemming for ru/es/en.** Mining works on folded surface forms, so
  inflected forms of one word ("opened/opens") are separate candidates. A stemmer needs matching to change too (rule
  stages match folded substrings). Candidate library: `snowballstemmer` (small, pure Python).
- **Per-chat weights.** One term can be useful in an IT chat and noise in a documents chat;
  today the lexicon is global. Needs `chat_id` scoping with inheritance from the global one.
- **Topic and "key moment" terms.** Only noise and question vocabulary are mined. Topics
  need either TF-IDF per thread or embeddings; revisit together with level 1.
- **Incremental mining.** Every run scans the whole corpus (fine up to ~100k messages).
  For millions: persistent n-gram counters updated per batch of new messages.
- **Pseudo-label drift guard.** Terms are mined using the filter's own verdicts as classes;
  a sampled review of what the filter *rejected* is needed to stop self-reinforcement.
- **Threshold tuning on real data.** Defaults (`LEARNING__MIN_*`) were set on synthetic
  chats only; they need a local pass over real exports (aggregates only).
- **AI as a proposer and judge** (the second half of the original idea): the lexicon already
  has `source=ai`; missing are the model calls, caching by text hash and the disagreement
  queue ("rules said noise, the model said useful").
- **Embeddings and hybrid search** (BM25 + vectors) for cross-language matches
  (Russian "rent" ↔ Spanish "alquiler").

### Operations

- **No authentication** on the panel (ADR-0004): fine on localhost, a prerequisite before
  any other exposure. The write guard compares `Origin` with the request URL, so a reverse
  proxy that rewrites scheme or host needs forwarded-header handling.
- **Worker wake-up on a dictionary change.** A decision in the panel only moves the lexicon
  revision; the pipeline applies it on the next `process` or worker cycle (hours). The worker
  should poll the revision every ~30 s and reprocess early.
- **Metrics history.** `chatradar eval` prints a report; storing runs in a table and a chart
  in the panel would show quality over time and per lexicon revision.
- **Messages carry no record of the lexicon revision they were classified with.** Needed
  only if per-message audit becomes important.
- **Undo for labels.** A label can be overwritten but not deleted from the panel.

### Panel

- **Lexicon page:** no page-size control (fixed 50), no `note` field when deciding, labels
  cannot carry `is_question` from the buttons.
- **Labeling** exists on the Review and Thread pages only, not in the Messages table.
- **Responsive polish:** tables stack below 900 px, which makes Quality long on a tablet;
  the "by noise reason" caption repeats its heading.
- **Not verified:** the 768 px light, 1280 px dark and 375 px dark combinations, AA
  contrast (chosen by eye, not measured), and the font on Linux.
- **Language switcher** and a second locale file beside `ru.json`.
- **Keyboard shortcuts** for the review page (j/k to move, n/u to label).
- **Real-browser end-to-end tests** (Playwright); today the panel is checked by static
  tests, `node --check` and a manual browser pass.
- **Favicon** and an app manifest.
