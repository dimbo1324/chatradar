# Security

## Reporting a vulnerability

Do not open a public issue. Use a
[private report](https://github.com/dimbo1324/chatradar/security/advisories/new).
Expect an answer within a few days.

## What counts as a secret here

| What | Where it lives | Why it matters |
|---|---|---|
| `chatimport.session` (Telethon) | `%LOCALAPPDATA%\ChatImport\session\` | **full access to the Telegram account** |
| `api_id` / `api_hash` | `%LOCALAPPDATA%\ChatImport\config.toml` | identify your application to Telegram |
| `chats.toml` | `%LOCALAPPDATA%\ChatImport\` | which private groups you are in |
| the `ChatImport` folder | the Desktop by default | messages and sender names of chat members |
| `chatimport.log` | `%LOCALAPPDATA%\ChatImport\logs\` | ids and counts only; never message text, names or invite links |
| exports | `<data root>\_exports\` | sender names only when exported with `--names` |

Protection: `.gitignore`, the pre-commit hook `forbid-secrets`, gitleaks locally and in CI,
and deny rules for AI assistants in `.claude/settings.json`.

If a session leaked: Telegram → Settings → Devices → terminate the session, then run
`chatimport login` again.

If the Desktop syncs to OneDrive, the archive leaves the machine: `run`, `status` and the
tray warn about it; move the data with `chatimport set-root <path> --move` or set
`output.root_dir` outside it.

Invite links in `chats.toml` are join tokens: the service shows them masked everywhere
else. Downloaded media with a risky extension get `.bin` appended and, on Windows, the
Mark-of-the-Web. On Linux and macOS the session, config and application folders are
owner-only.
