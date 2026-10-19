# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added

- Скелет проекта: uv, ruff, pyright strict, pytest, pre-commit, gitleaks.
- Лицензия MIT.
- `Settings` на pydantic-settings, structlog, доменная модель `Message` и порты.
- CLI на Typer с командами из плана (пока заглушки), веб-заглушка с `/healthz`.
- Alembic (async, batch-режим для SQLite).
- Dockerfile (multi-stage, uv, non-root), compose.yaml, justfile.
- GitHub Actions: CI (lint, typecheck, тесты на Linux/Windows, docker smoke), CodeQL,
  релиз образа в GHCR по тегу; Dependabot.
