# ЧатРадар — архитектура MVP без ИИ

Версия от 18.10.2026. Стадия: сбор и обработка сообщений («обычный сервис»), ИИ подключается позже.
Язык MVP: Python. Перед стартом перепроверить актуальные версии библиотек.

---

## 0. Как работает автоматический экспорт из Telegram

**Принцип.** Ручной экспорт в Telegram Desktop — это обычные запросы к API Telegram (протокол MTProto), только с кнопкой. Для автоматизации пишется собственный клиент, который логинится как пользователь и делает те же запросы. Бот не подходит: он не видит историю до своего добавления. У Telegram Desktop нет командной строки для экспорта, поэтому по расписанию его не запустить.

**Инструменты:**
- **Telethon** (Python) — основной выбор: зрелая библиотека, хорошая документация, сама обрабатывает FloodWait.
- Pyrogram — оригинал больше не поддерживается, живут только форки. Не брать.
- TDLib — официальная библиотека Telegram на C++, для MVP избыточна.
- Готовые CLI (например, `tdl` на Go) — чтобы быстро посмотреть данные.

**Как работает Telethon:**
1. Регистрируешь приложение на my.telegram.org и получаешь `api_id` и `api_hash`.
2. Первый вход: номер, код из Telegram, пароль 2FA. Создаётся файл `*.session`, дальше вход без кода. **Файл сессии = полный доступ к аккаунту**: не в git, хранить как пароль.
3. Чаты: публичные по `@username`, закрытые — через `get_dialogs`, если аккаунт в них состоит.
4. История: `iter_messages`, библиотека сама листает страницами по 100.
5. Докачка: хранить `last_id` по каждому чату и запрашивать `min_id=last_id`.
6. Запуск по расписанию.

Минимальный пример (Telethon 1.x):

```python
import asyncio
from telethon import TelegramClient

client = TelegramClient("collector", API_ID, API_HASH, flood_sleep_threshold=120)

async def fetch(chat, last_id=0):
    msgs = []
    async for m in client.iter_messages(chat, min_id=last_id, reverse=True):
        msgs.append({
            "id": m.id,
            "date": m.date.isoformat(),
            "author": m.sender_id,
            "text": m.message,
            "reply_to": m.reply_to.reply_to_msg_id if m.reply_to else None,
            "has_media": m.media is not None,
        })
    return msgs

async def main():
    async with client:          # первый запуск спросит телефон и код
        msgs = await fetch("some_public_chat")
        print(len(msgs), msgs[-1] if msgs else None)

asyncio.run(main())
```

`reverse=True` — сообщения идут от старых к новым, последнее обработанное имеет максимальный ID.

**Нюансы:**
- Правки и удаления докачка по `min_id` не видит. Простое решение: раз в сутки перекачивать последние 3–7 дней. Полноценное: постоянное подключение и события `NewMessage`, `MessageEdited`, `MessageDeleted`.
- Ссылки: публичный чат — `t.me/<username>/<id>`; закрытая супергруппа — `t.me/c/<id без -100>/<id сообщения>` (откроется только у участников).
- В форумах (группы с темами) `reply_to` может указывать на тему, а не на сообщение — проверить на своих чатах.
- Медиа сначала только отмечать (тип), скачивать (`download_media`) потом и выборочно.
- `client.takeout(...)` — режим экспорта Desktop с более мягкими лимитами для большой первичной выгрузки. Для 5–10 чатов не нужен.

**Основной или отдельный аккаунт:**

| | Основной аккаунт | Отдельный аккаунт |
|---|---|---|
| Плюсы | Уже во всех чатах, включая закрытые; старый аккаунт вызывает меньше подозрений | Риск изолирован от личного аккаунта |
| Минусы | Ограничения при перегрузке получит он; сессия = доступ к личному аккаунту | Нужен второй номер; вступать в закрытые чаты заново; новые аккаунты через API банят чаще |

Для экспериментов и периодической выгрузки 5–10 чатов можно использовать основной аккаунт, без агрессивной нагрузки. Отдельный аккаунт — когда сборщик переедет на сервер и будет работать круглосуточно или бот начнёт обслуживать других людей. Новому аккаунту дать несколько дней «пожить» как обычный, первую выгрузку делать медленно.

---

## 1. Архитектурные принципы

1. **Модульный монолит с портами и адаптерами (hexagonal architecture).** В центре доменная модель (`Message`, `Thread`, `Chat`) и интерфейсы-«порты»: источник сообщений, хранилище сырых данных, репозиторий сообщений, поисковый индекс. Telethon, SQLite, FastAPI — адаптеры. Домен о них не знает. SQLite → Postgres = новый адаптер репозитория, пайплайн не меняется.
2. **Сырые данные неизменяемы и лежат отдельно от базы.** Telegram → JSONL в `data/raw/`. База — производная: её можно удалить и пересобрать командой `rebuild` без обращения к Telegram.
3. **Пайплайн из идемпотентных стадий с версиями.** Любую стадию можно перезапускать; смена правил пересчитывает только нужное.
4. **Граница между модулями — формат данных, а не Python-объекты.** Тогда любую стадию можно переписать на Go/Rust: она будет читать и писать те же таблицы и файлы.
5. **Конфигурация через переменные окружения**, секреты только в `.env` (не в git).

---

## 2. Стек

| Задача | Инструмент | Почему |
|---|---|---|
| Python | 3.13 (3.14, если все зависимости собираются) | |
| Проект, зависимости, venv | **uv** | Быстрый, lock-файл, удобен в Docker |
| Линтер и форматтер | **ruff** | Заменяет flake8, isort, black |
| Типы | **pyright** или **mypy** (strict) | Строгая типизация |
| Тесты | **pytest**, pytest-asyncio | |
| Модели и конфиг | **pydantic v2**, **pydantic-settings** | Валидация на границах, конфиг из env |
| БД | **SQLAlchemy 2.0** (async) + **Alembic** | Одна абстракция для SQLite и Postgres, миграции |
| Драйверы | `aiosqlite` → позже `asyncpg` | Смена БД = смена `DATABASE_URL` |
| Telegram | **Telethon 1.x** | Основная стабильная ветка; у v2 другой API — проверить статус перед стартом |
| CLI | **Typer** | |
| Веб | **FastAPI** + **Jinja2** + **HTMX** | Простой интерфейс без отдельного фронтенда |
| Логи | **structlog** | Структурные логи, JSON в Docker |
| Язык текста | **lingua-py** | Различает ru/es даже на коротких фразах |
| Контейнеры | Docker + **docker compose** | |
| Качество | pre-commit, GitHub Actions | |

**Сознательно не используем на старте:** Celery, Redis, Kafka, React, микросервисы. Архитектура позволит добавить их позже без переписывания ядра.

---

## 3. Структура репозитория

```
chatradar/
├── pyproject.toml          # зависимости, настройки ruff/pyright/pytest
├── uv.lock
├── .env.example            # шаблон конфига (в git), .env — не в git
├── .gitignore
├── Dockerfile
├── compose.yaml
├── alembic.ini
├── justfile                # короткие команды: just test, just sync, just up
├── migrations/             # Alembic
├── data/                   # ВСЁ в .gitignore
│   ├── raw/telegram/<chat_id>/2026-10-18T23-50.jsonl
│   ├── sessions/collector.session
│   └── chatradar.db
├── src/chatradar/
│   ├── config.py           # Settings (pydantic-settings)
│   ├── domain/
│   │   ├── models.py       # Message, Thread, Chat, enums
│   │   └── ports.py        # Protocol-интерфейсы
│   ├── connectors/
│   │   ├── telegram/       # Telethon: client.py, mapper.py
│   │   └── tg_export/      # импорт JSON из Telegram Desktop
│   ├── storage/
│   │   ├── raw_jsonl.py    # RawStore на файлах
│   │   └── db/             # engine.py, tables.py, repositories.py, search_fts5.py
│   ├── pipeline/
│   │   ├── base.py         # интерфейс Stage, runner
│   │   ├── normalize.py
│   │   ├── noise.py
│   │   ├── enrich.py
│   │   ├── threads.py
│   │   └── index.py
│   ├── services/           # сценарии: sync, process, search, stats
│   ├── web/                # FastAPI: app.py, routes.py, templates/
│   └── cli.py              # Typer: точка входа
└── tests/
    ├── fixtures/           # обезличенные реальные сообщения
    ├── unit/
    └── integration/
```

`.gitignore` (главное):

```
data/
*.session
*.session-journal
.env
.venv/
```

Сессия и выгрузки лежат внутри проекта, но не в git. В Docker папка `data/` монтируется как volume.

---

## 4. Доменная модель и порты

```python
# domain/models.py
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict

class Source(StrEnum):
    TELEGRAM = "telegram"
    WHATSAPP_EXPORT = "whatsapp_export"

class MediaType(StrEnum):
    NONE = "none"; PHOTO = "photo"; VOICE = "voice"; VIDEO_NOTE = "video_note"
    DOCUMENT = "document"; STICKER = "sticker"; OTHER = "other"

class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Source
    chat_id: str            # строки: у разных мессенджеров разные ID
    msg_id: str
    author_id: str | None
    date: datetime          # всегда UTC, timezone-aware
    text: str
    reply_to: str | None
    topic_id: str | None    # тема в форумах Telegram
    media_type: MediaType
    is_forward: bool
    is_service: bool        # «вступил в группу» и т. п.
    edited_at: datetime | None
    link: str | None
    content_hash: str       # хэш значимых полей, чтобы ловить правки
```

```python
# domain/ports.py
from typing import Protocol, AsyncIterator

class Connector(Protocol):
    source: Source
    async def list_chats(self) -> list[ChatInfo]: ...
    def fetch(self, chat_id: str, since_id: str | None) -> AsyncIterator[RawRecord]: ...

class RawStore(Protocol):
    async def append(self, source: Source, chat_id: str, records: list[RawRecord]) -> None: ...
    def read(self, source: Source, chat_id: str) -> AsyncIterator[RawRecord]: ...

class MessageRepository(Protocol):
    async def upsert_many(self, msgs: list[Message]) -> UpsertResult: ...
    async def pending_for(self, stage: str, version: int, limit: int) -> list[StoredMessage]: ...
    async def mark(self, stage: str, version: int, updates: list[StageResult]) -> None: ...

class SearchIndex(Protocol):
    async def index(self, items: list[Indexable]) -> None: ...
    async def search(self, query: str, filters: SearchFilters) -> list[Hit]: ...
```

`Protocol` — структурная типизация: адаптеру не нужно наследоваться, достаточно нужных методов. В тестах вместо SQLite подставляется in-memory класс.

---

## 5. Стадии пайплайна

```
выгрузка → сырые данные → нормализация → фильтр шума → обогащение → склейка в обсуждения → индекс → (ИИ)
```

### Стадия 0. Сбор (sync)

Задача: докачать новые сообщения в `data/raw/`.

Для каждого чата:
1. Прочитать `last_id` из таблицы `sync_state`.
2. `iter_messages(chat, min_id=last_id, reverse=True)`, копить пачками по 500.
3. Каждую пачку дописать в JSONL-файл этого запуска.
4. **Только после записи файла** обновить `last_id` в базе.
5. Пауза 2–5 секунд между чатами.

Если процесс упал между шагами 3 и 4, часть сообщений скачается повторно — дублей не будет благодаря upsert на следующей стадии (at-least-once delivery + идемпотентная обработка).

Правки и удаления: раз в сутки перекачивать последние 7 дней (`offset_date`); изменения поймает `content_hash`.

Формат сырой записи:

```json
{"source":"telegram","chat_id":"-100123","fetched_at":"2026-10-18T23:50:00Z","payload":{"...": "m.to_dict()"}}
```

`m.to_dict()` содержит `datetime` и `bytes` — для `json.dumps` нужен свой `default=` (datetime → ISO, bytes → base64).

Первый логин — отдельная интерактивная команда `chatradar telegram login`, сессия в `data/sessions/`.

Тот же порт `Connector` реализует импорт JSON из Telegram Desktop — можно отлаживать весь пайплайн без подключения к Telegram.

### Стадия 1. Нормализация (normalize)

Задача: сырые записи → `Message` → upsert в `messages`.

- **Маппер — чистая функция** `telethon_dict → Message`, без I/O. Главный кандидат на тесты.
- Даты → UTC; текст → Unicode NFC, обрезка пробелов, схлопывание повторных переводов строк. Оригинал хранится в `text_raw`.
- Ссылка: `t.me/<username>/<id>` или `t.me/c/<id без -100>/<id>`.
- **Upsert с проверкой хэша:** новое — вставить; изменился `content_hash` — обновить и **сбросить версии всех последующих стадий**; хэш тот же — ничего не делать.

Upsert в SQLAlchemy для SQLite и Postgres — разные функции (`sqlite.insert` / `postgresql.insert` с `on_conflict_do_update`). Это единственное место, где код знает о диалекте, и оно спрятано в репозитории.

### Стадия 2. Фильтр шума (noise)

Задача: проставить `is_noise` и `noise_reason`. **Ничего не удалять.**

Список правил, каждое — функция `(msg, context) -> reason | None`, срабатывает первое подходящее:

```python
RULES: list[Rule] = [
    service_message,      # служебные события
    sticker_or_emoji_only,
    gratitude,            # «спасибо», «gracias», «+», «👍» — по словарю
    short_without_value,  # < 15 символов И не ответ на вопрос
    duplicate,            # хэш нормализованного текста уже был за 30 дней
    spam_patterns,        # ссылки + «заработок/пиши в лс», сообщения ботов
]
NOISE_VERSION = 3          # меняешь правила → увеличиваешь
```

- `context` даёт доступ к сообщению, на которое отвечают: «да» как ответ на вопрос ≠ «да» как флуд.
- Словари и пороги — в конфиге (YAML или константы), не в коде правил.
- Тесты табличные: «сообщение → ожидаемая причина». Каждый промах, найденный вручную, становится новой строкой теста.
- В вебе — страница «случайные 100 из шума / из не-шума» для ручной проверки.

### Стадия 3. Обогащение (enrich)

Дешёвые признаки без ИИ, только для `is_noise = false`:
- `lang`: ru / es / en / mixed (lingua-py; для текстов короче ~20 символов — `unknown`);
- `is_question`: «?» или вопросительные слова на ru и es;
- `urls`: извлечённые ссылки;
- `has_mention`: упоминания @username.

Телефоны и личные данные в отдельные поля не выносить.

### Стадия 4. Склейка в обсуждения (threads)

Задача: назначить каждому сообщению `thread_id`.

1. **Reply-связи → компоненты связности** (union-find).
2. **Сообщения без reply** присоединяются к предыдущему обсуждению того же чата (и той же темы форума), если пауза меньше `GAP` (начать с 30 минут). Иначе — новое обсуждение.
3. **Стабильный ID:** `thread_id = f"{chat_id}:{root_msg_id}"`, корень — самое раннее сообщение.
4. **Инкрементальность:** пересчитывается только хвост чата — новые сообщения плюс перекрытие в 2 дня.

Результат: таблица `threads` (id, чат, начало, конец, число сообщений, `has_question`) и `messages.thread_id`.

Стадия изолирована за интерфейсом — позже можно подставить другой алгоритм (например, с эмбеддингами) и сравнить качество.

### Стадия 5. Индексация (index)

- SQLite: FTS5 по `messages.text` и по склеенному тексту обсуждения. Для русского без морфологии на старте — поиск по префиксу (`квартир*`).
- Postgres позже: `tsvector` + GIN-индекс.
- Обе реализации — за портом `SearchIndex`.
- Позже: эмбеддинги, `sqlite-vec` → `pgvector`.

### Оркестрация стадий

```python
class Stage(Protocol):
    name: str            # "noise"
    version: int         # NOISE_VERSION
    depends_on: str      # "normalize"
    async def process(self, batch: list[StoredMessage]) -> list[StageResult]: ...
```

Runner:

```
для каждой стадии по порядку:
    пока есть сообщения, где <stage>_v IS NULL или < version
                         и предыдущая стадия пройдена:
        взять пачку (500) → process → записать результат и версию одной транзакцией
```

В `messages` колонки `normalize_v, noise_v, enrich_v, thread_v, index_v`. Состояние пайплайна видно одним SQL-запросом.

При масштабировании runner заменяется очередью (Redis Streams, NATS), интерфейс `Stage` остаётся.

---

## 6. База данных и переход SQLite → Postgres

Схема для старта:

```
chats         (source, chat_id, title, username)
sync_state    (source, chat_id, last_id, last_sync_at)
messages      (source, chat_id, msg_id, author_id, date, text, text_raw, reply_to, topic_id,
               media_type, is_forward, is_service, edited_at, link, content_hash,
               lang, is_question, is_noise, noise_reason, thread_id,
               normalize_v, noise_v, enrich_v, thread_v, index_v)
threads       (thread_id, source, chat_id, started_at, ended_at, root_msg_id, msg_count, has_question)
messages_fts  (FTS5)
```

- **SQLAlchemy 2.0 Core** для пайплайна (массовые upsert). ORM — в веб-части, где удобнее.
- **Alembic** с первого дня. Для SQLite — `render_as_batch=True` (иначе не работает `ALTER TABLE`).
- **PRAGMA для SQLite** при подключении: `journal_mode=WAL; foreign_keys=ON; busy_timeout=5000; synchronous=NORMAL`. WAL позволяет вебу читать, пока воркер пишет.
- **Пишет в SQLite один процесс** (воркер), веб только читает. В Postgres это ограничение исчезает.
- Диалектно-зависимый код (upsert, FTS) — только в `storage/db/`.

Переход на Postgres:
1. добавить сервис `db` в compose;
2. поменять `DATABASE_URL`;
3. `alembic upgrade head`;
4. `chatradar rebuild` — пересобрать базу из сырых JSONL.

---

## 7. Веб-интерфейс (FastAPI + HTMX)

Цель — видеть, что происходит внутри. Это отладочная панель, а не продукт.

1. **Чаты:** список, число сообщений, последняя синхронизация, кнопка «синхронизировать».
2. **Пайплайн:** сколько сообщений на каждой стадии, сколько ждёт обработки, версии правил.
3. **Сообщения:** таблица с фильтрами (чат, дата, язык, шум, причина шума, вопрос), подгрузка через HTMX.
4. **Обсуждение:** сообщения треда лентой с отступами по reply и ссылками в Telegram.
5. **Поиск:** запрос → найденные обсуждения.
6. **Проверка фильтра:** случайные 100 из шума и из не-шума.

HTMX: только Python и HTML-шаблоны, без сборки фронтенда. Будущий веб-кабинет — отдельно на React/Next.js поверх того же FastAPI как JSON API.

Будущий Telegram-бот — такой же адаптер интерфейса, как веб: вызывает те же сервисы `search`, `stats`, `digest`. Ядро менять не придётся.

---

## 8. CLI

```
chatradar telegram login                  # первый вход, интерактивно
chatradar chats add @montevideo_ru        # добавить чат в список
chatradar chats list
chatradar import tg-export ./result.json  # импорт выгрузки из Desktop
chatradar sync [--chat ID] [--recheck-days 7]
chatradar process [--stage noise] [--reset-stage noise]
chatradar rebuild                         # база заново из data/raw
chatradar web                             # uvicorn
chatradar worker                          # цикл: sync → process → пауза
```

Каждая команда — тонкая обёртка над функцией из `services/`. Логики в CLI нет.

---

## 9. Docker

**Dockerfile** (multi-stage с uv):

```dockerfile
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
WORKDIR /app
RUN useradd -m app
COPY --from=builder --chown=app /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER app
ENTRYPOINT ["chatradar"]
```

Тег `uv:latest` в проекте закрепить на конкретной версии.

**compose.yaml:**

```yaml
services:
  web:
    build: .
    command: web --host 0.0.0.0 --port 8000
    ports: ["127.0.0.1:8000:8000"]   # только локально
    env_file: .env
    volumes: ["./data:/app/data"]

  worker:
    build: .
    command: worker
    env_file: .env
    volumes: ["./data:/app/data"]
    restart: unless-stopped

  # позже:
  # db:
  #   image: postgres:17
  #   volumes: ["pgdata:/var/lib/postgresql/data"]
```

Первый логин в Telegram:

```
docker compose run --rm -it worker telegram login
```

Сессия появится в `./data/sessions/` и переживёт пересборку контейнеров.

`worker` при старте выполняет `alembic upgrade head`, затем бесконечный цикл: синхронизация раз в N часов, обработка после каждой синхронизации. Для MVP хватит `asyncio`-цикла со `sleep`, без отдельного планировщика.

---

## 10. Качество кода

- **pyproject.toml:** ruff с правилами `E, F, I, UP, B, SIM, ASYNC, RUF`; pyright в strict-режиме.
- **pre-commit:** ruff, ruff-format, pyright, запрет коммита `.env` и `*.session`.
- **Тесты:**
  - unit — маппер, правила шума, алгоритм склейки, на обезличенных реальных фикстурах;
  - integration — весь пайплайн на in-memory SQLite;
  - Telegram в тестах не вызывается никогда, вместо него фейковый `Connector`.
- **CI** (GitHub Actions): lint → typecheck → tests на каждый push.
- **Логи:** structlog; в каждом событии `stage`, `chat_id`, `count`, `duration_ms`.
- **Конфиг:** один класс `Settings` (pydantic-settings); `.env.example` в репозитории, `.env` — нет.

---

## 11. Про Go, C++ и Rust

Узкие места проекта — **лимиты Telegram API** и **скорость и стоимость LLM**, а не Python. Фильтр на правилах обработает сотни тысяч сообщений за секунды. Переписывать на другой язык — только когда профилирование покажет конкретное горячее место. Кандидаты:
- локальное вычисление эмбеддингов (но там и так C++/Rust внутри библиотек);
- высоконагруженный сборщик на тысячи чатов — подходит Go.

Граница между модулями — JSONL и таблицы БД, поэтому стадию можно переписать отдельно. Заранее делать не стоит.

---

## 12. Порядок реализации

| Шаг | Что сделать | Результат |
|---|---|---|
| 1 | Скелет: uv, ruff, pyright, pytest, pre-commit, структура папок, `Settings` | Пустой проект, проходящий CI |
| 2 | Домен и порты; импорт JSON из Telegram Desktop; RawStore на JSONL | Данные в `data/raw/` без Telethon |
| 3 | SQLAlchemy, Alembic, таблицы, нормализация с upsert | Сообщения в SQLite |
| 4 | Runner стадий; фильтр шума и обогащение с тестами | Размеченные сообщения |
| 5 | Веб: «чаты», «пайплайн», «сообщения» | Видно, что происходит |
| 6 | Склейка в обсуждения, FTS5, страница поиска | Работающий поиск |
| 7 | Telethon-коннектор, `login`, `sync`, worker | Автоматическая докачка |
| 8 | Docker и compose | `docker compose up` поднимает всё |

После шага 8 — полноценный сервис без ИИ. ИИ-стадии (разметка тем, эмбеддинги, ответы) подключаются следующими стадиями по тому же интерфейсу `Stage`.
