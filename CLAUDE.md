# CLAUDE.md

Контекст для ИИ-ассистентов. Общайся по-русски, коротко и по шагам; не усложняй раньше времени;
честно говори, если идея слабая.

- Видение: `docs/vision.md`. Архитектура и порядок шагов: `docs/architecture.md` (§12).
- Проверка перед коммитом: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`.
- Зависимости только через `uv add` / `uv add --dev`; `uv.lock` коммитится.
- `chatradar.domain` не импортирует адаптеры (Telethon, SQLAlchemy, FastAPI).
- Даты — timezone-aware UTC. Стадии пайплайна идемпотентны и версионированы.
- Никогда не читать и не коммитить `.env`, `*.session`, содержимое `data/`.
- В тесты — только обезличенные фикстуры; Telegram в тестах не вызывается.
