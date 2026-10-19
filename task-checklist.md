# Task: synthetic chat data modelled on the owner's real chats (ru, es, en)

Owner instruction of 2026-10-19: study the chat exports in the owner's local folder and build
synthetic messages based on them, with Russian, Spanish and English.

Privacy constraint (applied throughout): the real exports are personal data of chat
members. They are extracted only into the session's temporary folder, studied only as
aggregates, and nothing real (message, name, username) reaches the repository or a report.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Two RAR5 archives extracted with WinRAR's UnRAR into the session scratchpad (the built-in
  tar cannot read RAR5 or Cyrillic paths)
+ Profile of 8 unique chats (~177k messages, 2022-07 → 2026-10; two exports were exact
  duplicates): languages, reply/edit/question/short/media/service/forward rates, length and
  gap distributions, reply depth, topic vocabulary, Spanish terms inside Russian text,
  generic short replies used by at least 15 authors
- This checklist was not committed before the work started (small task, one sitting)

## 2. Implementation

+ `tests/fixtures/synthetic/phrasebank.json`: invented phrases in ru/es/en for banks,
  documents, housing, health, work, telecom, meetups, IT; short replies, gratitude,
  greetings, flood, spam, forwards, openers and closers for variety
+ `scripts/generate_synthetic.py`: deterministic generator (stdlib only), four chats —
  ru banks and documents, ru IT with English, es community, en expats — with interleaved
  threads, reply chains, unlinked answers, edits, photos, voice, video notes, stickers,
  animations, joins, forwards, spam and reposts
+ Calibration against the profile: replies 60–65 % (real 53–72 %), edits 21–28 % (~28 %),
  links 2–4 % (2–3.5 %), short 5–10 % (~7.5 %); questions 22–27 % (real ~18 %, kept higher
  on purpose for search tests)
+ `just synthetic`, `just synthetic-check` (in `just check`, CI and pre-commit), `just demo`

## 3. Findings fixed in the product (found by running the synthetic chats)

+ Duplicate rule flagged repeated short replies ("why?", "yes") — now only texts of 20+
  characters
+ Repeated spam was labelled `duplicate` — spam now runs before duplicate
+ English "Earn $500 a week working from home, DM me" was not spam — lexicon fixed
+ A Russian "thanks, you really helped" was not gratitude — lexicon fixed
+ Noise stage version 3; regression rows and a stage test added
- English prefix search matches longer words ("account" → "accountant"): a trade-off of the
  prefix rule that helps Russian and Spanish inflection; left for level 1 (recorded in
  `docs/decisions.md`)

## 4. Verification and completion

+ Generator tests: determinism, committed files in sync, every message parses and maps,
  rates inside realistic bounds, all three languages present
+ Whole pipeline on the four chats: ~1 680 messages, ~14 % noise, 240+ threads, search in
  three languages
+ `just check` green (499 tests); hooks green
+ Docs: README, project map, commands, domain rules, decisions, changelogs
- Real exports remain extracted in the session's temporary folder, outside the repository
+ Final report to the owner
