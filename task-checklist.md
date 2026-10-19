# Task: the web panel's interface in Russian

Owner instruction of 2026-10-19: make the frontend interface Russian; commit and push. The
data stays synthetic only.

Marks: `[ ]` open, `+` done, `-` not done or partially done (with a note).

## 1. Preparation

+ Read every frontend module and the web tests
+ Language policy: the rule "everything tracked is English" needs an exception; the owner
  asked for it, so it is recorded (`docs/decisions.md`, `.ai/CHANGELOG.md`) and kept narrow:
  UI text as data, code stays English
- Branch `feat/ru-ui` and this checklist were created together with the work, not before

## 2. Implementation

+ `static/js/i18n.js`: `t()` (plain), `tn()` (Russian plurals through `Intl.PluralRules`),
  `tEnum()` (server values, shown raw when unknown), `num()` (ru number format)
+ `static/i18n/ru.json`: about 140 keys — navigation, filters, tables, states, errors,
  noise reasons, stages, media types, sources, languages
+ Every view, the router, filters, `dom.js` and `api.js` use keys only; the menu is built
  from the routes; `index.html` is Russian shell text; `<html lang="ru">`
+ Dates day.month.year; API errors explained by HTTP status (404, 422, 5xx) because the
  server's detail text is English
+ `check_language.py` allows `static/i18n/` and `static/index.html`

## 3. Verification

+ `tests/unit/web/test_i18n.py`: valid locale, every key used by the code exists, no unused
  keys, plural keys used with `tn` and plain keys with `t`, equal placeholders across plural
  forms, every backend enum (noise reasons, stages, media types, sources) is translated,
  texts are Russian, assets served
+ Browser check on the demo database: chats, processing, messages with filters, review,
  search with correct plural forms of "discussions", thread, 404 error text — all in Russian
+ `just check` green (515 tests), hooks green
- Not checked: other browsers; the dark/light themes were not re-reviewed (CSS untouched)
- Not done: a language switcher (one locale only; the design allows another file beside
  `ru.json`)

## 4. Completion

+ Docs: project map, interfaces agent (and generated Codex mirror), `docs/api.md`,
  decisions, README, changelogs
+ Fast-forward merge into `main` and push (explicitly requested)
