# Безопасность

## Сообщить об уязвимости

Не создавайте публичный issue. Используйте
[приватный отчёт](https://github.com/dimbo1324/chatradar/security/advisories/new).
Ответ — в течение нескольких дней.

## Что в проекте считается секретом

| Что | Где лежит | Почему важно |
|---|---|---|
| `*.session` (Telethon) | `data/sessions/` | **полный доступ к аккаунту Telegram** |
| `api_id` / `api_hash` | `.env` | идентифицируют ваше приложение в Telegram |
| ключи LLM API | `.env` | деньги |
| выгрузки чатов | `data/raw/` | персональные данные участников чатов |

Защита: `.gitignore`, pre-commit-хук `forbid-secrets`, gitleaks локально и в CI.

Если сессия утекла: Telegram → Настройки → Устройства → завершить сеанс, затем заново
`chatradar telegram login`.
