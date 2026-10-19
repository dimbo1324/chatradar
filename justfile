# Project commands. Install just: winget install Casey.Just | brew install just
# List them: just

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

default:
    @just --list --unsorted

# Install dependencies and the git hook, once per clone
setup:
    uv sync
    uv run pre-commit install

# Install dependencies exactly as uv.lock says
sync:
    uv sync

# Format code and apply safe lint fixes
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Lint and format check without changes
lint:
    uv run ruff check .
    uv run ruff format --check .

# Strict type check
typecheck:
    uv run pyright

# Tests; arguments go to pytest: just test -k noise
test *args:
    uv run pytest {{ args }}

# Tests with coverage
cov:
    uv run pytest --cov --cov-report=term-missing --cov-report=xml

# Regenerate AGENTS.md and the .codex mirror from .ai/ and .claude/
agents:
    uv run python scripts/sync_agents.py

# Verify AGENTS.md and the .codex mirror are current
agents-check:
    uv run python scripts/sync_agents.py --check

# No Cyrillic outside the allowed data paths
language:
    uv run python scripts/check_language.py

# Regenerate the synthetic chat exports in tests/fixtures/synthetic/
synthetic:
    uv run python scripts/generate_synthetic.py

# Verify the committed synthetic exports match the generator
synthetic-check:
    uv run python scripts/generate_synthetic.py --check

# Load every synthetic chat into the local database (data/) for manual testing
demo:
    uv run chatradar import tg-export tests/fixtures/synthetic/ru_banks_docs.json --username demo_banks_docs
    uv run chatradar import tg-export tests/fixtures/synthetic/ru_it.json --username demo_it_uy
    uv run chatradar import tg-export tests/fixtures/synthetic/es_comunidad.json --username demo_comunidad
    uv run chatradar import tg-export tests/fixtures/synthetic/en_expats.json --username demo_expats_en

# The full gate: everything CI checks
check: lint typecheck test agents-check language synthetic-check

# Read-only toolchain check
doctor:
    python scripts/doctor.py

# Every pre-commit hook over the whole repository
hooks:
    uv run pre-commit run --all-files

# Apply migrations
migrate:
    uv run alembic upgrade head

# New migration: just revision "add messages table"
revision message:
    uv run alembic revision --autogenerate -m "{{ message }}"

# Debug panel on 127.0.0.1:8000
web:
    uv run chatradar web

# Docker: build and start
up:
    docker compose up -d --build

# Docker: stop
down:
    docker compose down

# Docker: follow logs
logs *args:
    docker compose logs -f {{ args }}

# First Telegram login inside the container
login:
    docker compose run --rm -it worker telegram login
