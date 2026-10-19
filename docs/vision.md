# ChatRadar — Product Vision

## Problem

Useful information for migrants (documents, residence permits, banks, housing, jobs,
tradespeople, doctors) is scattered across dozens of Telegram, WhatsApp and other chats:

- reading everything by hand takes too long;
- there is a lot of noise: flood, arguments, "thanks" and "+";
- both the answer and the person who knows the topic are hard to find;
- community meetups often have no agenda.

## Solution

The system collects messages itself, filters out noise and:

1. answers a question briefly — **with links to the source messages and their dates**;
2. weekly or monthly, lists the hot topics and the "evergreen questions" — a ready meetup
   agenda;
3. suggests whom to ask (who was recommended in the chats);
4. notifies about subscribed topics.

**The core principle:** every statement carries a link to a message and its date.
Information in chats goes stale quickly. No messages found → "no answer in the chats", never
an invented one.

## Interfaces

The main one is a Telegram bot (`/topic`, `/digest`, `/agenda`, `/subscribe`). Later: a web
dashboard for long reports, filters and charts, and an API for community admins and
partners.

## Product levels

Each level is useful on its own; move to the next only if the previous one is actually used.

| Level | Scope | Key items |
|---|---|---|
| 0 — MVP | for the owner | Telethon, 5–10 chats, SQLite, noise filter, thread grouping, search plus a short LLM answer with links, weekly digest |
| 1 | for friends | semantic search, automatic topic labels, evergreen-question base, subscriptions, allowlist of users, ru/es/en, voice transcription |
| 2 | platform | WhatsApp import and Discord connectors, web dashboard, links to official sources, answer ratings, photos/PDF/links |
| 3 | product for communities | chat admin panel, auto-answers with admin consent, templates for other cities, public API |

## Sources

| Messenger | Path |
|---|---|
| Telegram | a user account through Telethon (MTProto) — the full history |
| Discord | the official Bot API, if an admin added the bot |
| WhatsApp | only the "Export chat" file import (unofficial clients risk a ban) |
| Any | a universal "import a file" connector |

## Risks and rules

- **Telegram limits** → pauses, FloodWait respected, a separate account for round-the-clock
  collection.
- **Stale or wrong advice** → a date and a link in every answer; for documents, an official
  source too.
- **AI hallucinations** → answers are built only from found messages.
- **Personal data** (Uruguay, Ley 18.331) → no profiles of people; a specialist directory
  only by consent; raw messages are never published — only summaries and links.
- **Chat admins** → agree with them before a public launch and offer value (an admin panel).

## Metrics

From day one, track weekly active users and retention (how many people come back), not the
number of sign-ups.

## Open questions

Kept in `docs/decisions.md`.
