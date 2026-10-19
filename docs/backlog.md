# Backlog: deferred work

Things that were considered and deliberately not done yet, so they are not lost. Newest
sections first. When an item ships, move it to `CHANGELOG.md`; when it is dropped, say why.

## From the learning-lexicon task (2026-10-19)

Context: `docs/adr/0003-learning-lexicon.md`, `docs/adr/0004-panel-write-path.md`.

### Learning

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

- **Worker wake-up on a dictionary change.** A decision in the panel only moves the lexicon
  revision; the pipeline applies it on the next `process` or worker cycle (hours). The worker
  should poll the revision every ~30 s and reprocess early.
- **Metrics history.** `chatradar eval` prints a report; storing runs in a table and a chart
  in the panel would show quality over time and per lexicon revision.
- **Messages carry no record of the lexicon revision they were classified with.** Needed
  only if per-message audit becomes important.
- **Undo for labels.** A label can be overwritten but not deleted from the panel.

### Panel

- **Language switcher** and a second locale file beside `ru.json`.
- **Keyboard shortcuts** for the review page (j/k to move, n/u to label).
- **Real-browser end-to-end tests** (Playwright); today the panel is checked by static
  tests, `node --check` and a manual browser pass.
- **Favicon** and an app manifest.
