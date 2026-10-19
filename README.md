# ЧатРадар

[![CI](https://github.com/dimbo1324/chatradar/actions/workflows/ci.yml/badge.svg)](https://github.com/dimbo1324/chatradar/actions/workflows/ci.yml)
[![CodeQL](https://github.com/dimbo1324/chatradar/actions/workflows/codeql.yml/badge.svg)](https://github.com/dimbo1324/chatradar/actions/workflows/codeql.yml)
![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Собирает сообщения из чатов мессенджеров, отсеивает шум и отвечает на вопросы
**со ссылками на исходные сообщения и их датами**. Дайджесты горячих тем, «вечные вопросы»,
подсказки, к кому обратиться.

> **Статус:** pre-alpha. Готов скелет проекта (шаг 1 плана), функциональность в разработке.
> Подробнее — [видение продукта](docs/vision.md) и [архитектура](docs/architecture.md).

## Как это устроено

```
КОННЕКТОРЫ ──▶ data/raw/*.jsonl ──▶ normalize ─▶ noise ─▶ enrich ─▶ threads ─▶ index ──▶ ИНТЕРФЕЙСЫ
(Telegram,      (неизменяемый       └──────────── идемпотентные стадии с версиями ────┘   (веб, бот, API)
 импорт файлов)  источник истины)                       БД (SQLite → Postgres)
```

- **Модульный монолит с портами и адаптерами** — домен не знает о Telethon, SQLite и FastAPI
  ([ADR-0001](docs/adr/0001-modular-monolith-hexagonal.md)).
- **Сырые данные неизменяемы**, база — производная и пересобирается `chatradar rebuild`.
- **Граница между модулями — формат данных**, поэтому любую стадию можно вынести или переписать.

## Быстрый старт

Нужны [uv](https://docs.astral.sh/uv/) и (по желанию) [just](https://just.systems/) и Docker.

```bash
git clone https://github.com/dimbo1324/chatradar.git
```

```bash
cd chatradar
```

```bash
uv sync
```

```bash
uv run pre-commit install
```

```bash
cp .env.example .env
```

```bash
uv run chatradar --help
```

`uv` сам поставит Python 3.13 из `.python-version`.

### Telegram

1. Зарегистрируйте приложение на [my.telegram.org](https://my.telegram.org) → `api_id`, `api_hash`.
2. Впишите их в `.env` (`CHATRADAR_TELEGRAM__API_ID`, `CHATRADAR_TELEGRAM__API_HASH`).
3. `chatradar telegram login` — сессия появится в `data/sessions/`.

> **Файл `*.session` = полный доступ к аккаунту.** Он в `.gitignore`, pre-commit не даст его закоммитить.
> Храните его как пароль.

### Docker

```bash
docker compose up -d --build
```

```bash
docker compose run --rm -it worker telegram login
```

Веб-панель: <http://127.0.0.1:8000> (только локально), healthcheck — `/healthz`.
Каталог `./data` монтируется в контейнеры и переживает пересборку.

## Команды разработки

| `just …` | Что делает |
|---|---|
| `setup` | зависимости + git-хуки |
| `fmt` / `lint` | ruff format / ruff check |
| `typecheck` | pyright (strict) |
| `test` / `cov` | pytest / с покрытием |
| `check` | всё, что проверяет CI |
| `migrate` / `revision "msg"` | Alembic |
| `up` / `down` / `logs` / `login` | Docker Compose |

Без `just` — те же команды через `uv run …` (см. [`justfile`](justfile)).

## CLI

```
chatradar telegram login                  # первый вход, интерактивно
chatradar chats add @some_chat            # добавить чат
chatradar chats list
chatradar import tg-export ./result.json  # импорт выгрузки Telegram Desktop
chatradar sync [--chat ID] [--recheck-days 7]
chatradar process [--stage noise] [--reset-stage noise]
chatradar rebuild                         # база заново из data/raw
chatradar web                             # веб-панель
chatradar worker                          # цикл: sync → process → пауза
```

## Структура

```
src/chatradar/
├── config.py        # Settings (pydantic-settings), всё из env
├── logs.py          # structlog: консоль в dev, JSON в prod
├── domain/          # Message, Chat, порты-Protocol — без внешних зависимостей
├── connectors/      # telegram (Telethon), tg_export (JSON из Desktop)
├── storage/         # raw JSONL + db (SQLAlchemy 2.0, FTS5)
├── pipeline/        # стадии: normalize, noise, enrich, threads, index
├── services/        # сценарии: sync, process, search, stats
├── web/             # FastAPI + Jinja2 + HTMX
└── cli.py           # Typer
migrations/          # Alembic (async, batch-режим для SQLite)
tests/{unit,integration,fixtures}
docs/                # видение, архитектура, ADR
```

## План

| Шаг | Что | Статус |
|---|---|---|
| 1 | Скелет: uv, ruff, pyright, pytest, pre-commit, CI, `Settings` | ✅ |
| 2 | Домен и порты, импорт JSON из Telegram Desktop, RawStore на JSONL | ⏳ |
| 3 | SQLAlchemy, Alembic, таблицы, нормализация с upsert | |
| 4 | Runner стадий, фильтр шума и обогащение | |
| 5 | Веб: чаты, пайплайн, сообщения | |
| 6 | Склейка в обсуждения, FTS5, поиск | |
| 7 | Telethon-коннектор, `login`, `sync`, worker | |
| 8 | Docker и compose для всего сервиса | |

## Данные и приватность

- Сообщения хранятся только локально в `data/` (вне git).
- В тестовых фикстурах — только обезличенные сообщения.
- Наружу никогда не публикуются сырые сообщения — только выжимки и ссылки.
- Профили людей не собираются (Ley 18.331 о защите персональных данных, Уругвай).

## Участие

См. [CONTRIBUTING.md](CONTRIBUTING.md). Об уязвимостях — [SECURITY.md](SECURITY.md).
