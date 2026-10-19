"""Cross-site protection for write requests (ADR-0004)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REQUESTED_WITH = "X-Requested-With"
REQUESTED_WITH_VALUE = "chatradar"
DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_parts(scheme: str, netloc: str) -> tuple[str, str | None, int | None]:
    parts = urlsplit(f"{scheme}://{netloc}")
    try:
        port = parts.port
    except ValueError:
        port = -1
    return scheme, parts.hostname, port or DEFAULT_PORTS.get(scheme)


def _same_origin(origin: str, request: Request) -> bool:
    parts = urlsplit(origin)
    if not parts.scheme or not parts.netloc or parts.path or parts.query or parts.fragment:
        return False
    own = _origin_parts(request.url.scheme, request.url.netloc)
    return _origin_parts(parts.scheme, parts.netloc) == own


def _forbidden(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=403)


async def write_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method in SAFE_METHODS:
        return await call_next(request)
    if request.headers.get(REQUESTED_WITH) != REQUESTED_WITH_VALUE:
        return _forbidden(f"Missing header {REQUESTED_WITH}: {REQUESTED_WITH_VALUE}")
    origin = request.headers.get("origin")
    if origin is not None and not _same_origin(origin, request):
        return _forbidden("Cross-origin request refused")
    return await call_next(request)
