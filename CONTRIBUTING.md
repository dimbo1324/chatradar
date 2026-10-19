# Как вносить изменения

## Окружение

```bash
just setup        # uv sync + pre-commit install
just check        # то же, что CI: lint → typecheck → tests
```

## Ветки и коммиты

- `main` всегда зелёная; работа — в ветках `feat/…`, `fix/…`, `chore/…`, `docs/…`.
- Коммиты в стиле [Conventional Commits](https://www.conventionalcommits.org/ru/):
  `feat(noise): правило для благодарностей на испанском`.
- PR маленькие, одна мысль на PR. CI должен пройти до слияния.

## Правила кода

- **Типы строгие** (pyright strict). `Any` — только на границе с нетипизированными библиотеками.
- **Домен чистый:** `chatradar.domain` не импортирует Telethon, SQLAlchemy, FastAPI.
- **Диалект БД** (upsert, FTS) — только в `chatradar.storage.db`.
- **CLI, веб, бот — тонкие обёртки** над `chatradar.services`. Логики в них нет.
- **Даты всегда timezone-aware в UTC.** Naive datetime ловит ruff (`DTZ`) и pydantic (`AwareDatetime`).
- **Стадии идемпотентны.** Изменили правила стадии — увеличьте её `version`.
- **Схема БД меняется только миграцией:** `just revision "описание"`.

## Тесты

- `tests/unit` — чистые функции: мапперы, правила шума, склейка. Табличные тесты
  («сообщение → ожидаемая причина»); каждый найденный руками промах — новая строка.
- `tests/integration` — пайплайн целиком на in-memory SQLite.
- **Telegram в тестах не вызывается никогда** — вместо него фейковый `Connector`.
- Фикстуры в `tests/fixtures` — **только обезличенные** сообщения: без имён, телефонов, username.

## Архитектурные решения

Значимое решение (новая зависимость, смена хранилища, новый сервис) — короткий ADR в `docs/adr/`.

## Релизы

Версия в `pyproject.toml` (SemVer). Тег `vX.Y.Z` → GitHub Actions собирает образ в GHCR
и создаёт GitHub Release с автоматическими заметками. Изменения — в [CHANGELOG.md](CHANGELOG.md).
