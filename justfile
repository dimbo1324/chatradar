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

# The full gate: everything CI checks
check: lint typecheck test agents-check language

# Read-only toolchain check
doctor:
    python scripts/doctor.py

# Every pre-commit hook over the whole repository
hooks:
    uv run pre-commit run --all-files
