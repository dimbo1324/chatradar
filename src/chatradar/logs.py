"""Structured logs (structlog): readable in dev, JSON in prod.

Convention: pipeline events always carry `stage`, `chat_id`, `count`, `duration_ms`.
"""

from __future__ import annotations

import logging
import sys

import structlog

from chatradar.config import Environment, LogLevel


def configure_logging(env: Environment, level: LogLevel = "INFO") -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: structlog.types.Processor
    if env is Environment.PROD:
        shared.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        # Resolve sys.stderr on every log call: a cached logger would keep writing to a
        # stream that was replaced and closed (test runners, reconfigured consoles).
        logger_factory=_stderr_logger,
        cache_logger_on_first_use=False,
    )


def _stderr_logger(*_args: object) -> structlog.PrintLogger:
    return structlog.PrintLogger(sys.stderr)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
