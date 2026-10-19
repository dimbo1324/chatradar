# Security

## Reporting a vulnerability

Do not open a public issue. Use a
[private report](https://github.com/dimbo1324/chatradar/security/advisories/new).
Expect an answer within a few days.

## What counts as a secret here

| What | Where it lives | Why it matters |
|---|---|---|
| `*.session` (Telethon) | `data/sessions/` | **full access to the Telegram account** |
| `api_id` / `api_hash` | `.env` | identify your application to Telegram |
| LLM API keys | `.env` | money |
| chat exports | `data/raw/` | personal data of chat members |

Protection: `.gitignore`, the pre-commit hook `forbid-secrets`, gitleaks locally and in CI,
and deny rules for AI assistants in `.claude/settings.json`.

If a session leaked: Telegram → Settings → Devices → terminate the session, then run
`chatradar telegram login` again.
