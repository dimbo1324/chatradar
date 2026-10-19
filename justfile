# Короткие команды проекта. Установка just: winget install Casey.Just | brew install just
# Список: just

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

default:
    @just --list --unsorted

# Установить зависимости и git-хуки
setup:
    uv sync
    uv run pre-commit install

# Обновить lock-файл и зависимости
sync:
    uv sync

# Отформатировать код
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Линтер без правок
lint:
    uv run ruff check .
    uv run ruff format --check .

# Строгая проверка типов
typecheck:
    uv run pyright

# Тесты (аргументы пробрасываются в pytest: just test -k noise)
test *args:
    uv run pytest {{ args }}

# Тесты с покрытием
cov:
    uv run pytest --cov --cov-report=term-missing --cov-report=xml

# Всё, что проверяет CI
check: lint typecheck test

# Все pre-commit хуки по всему репозиторию
hooks:
    uv run pre-commit run --all-files

# Применить миграции
migrate:
    uv run alembic upgrade head

# Новая миграция: just revision "add messages table"
revision message:
    uv run alembic revision --autogenerate -m "{{ message }}"

# Веб-панель локально
web:
    uv run chatradar web

# Docker: собрать и поднять
up:
    docker compose up -d --build

# Docker: остановить
down:
    docker compose down

# Docker: логи
logs *args:
    docker compose logs -f {{ args }}

# Первый вход в Telegram внутри контейнера
login:
    docker compose run --rm -it worker telegram login
