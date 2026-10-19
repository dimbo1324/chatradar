from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chatradar import __version__
from chatradar.config import get_settings
from chatradar.services.container import open_runtime
from chatradar.web.api import router
from chatradar.web.feedback_api import router as feedback_router
from chatradar.web.guard import write_guard

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

    from chatradar.services.feedback import FeedbackServices
    from chatradar.services.queries import ReadServices

# Windows' registry has no entry for woff2, so StaticFiles would serve fonts as octet-stream.
mimetypes.add_type("font/woff2", ".woff2")

STATIC_DIR = Path(__file__).parent / "static"
DOCS_URL = "/api/docs"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@asynccontextmanager
async def _real_services(app: FastAPI) -> AsyncGenerator[None]:
    async with open_runtime(get_settings()) as runtime:
        app.state.read = runtime.read
        app.state.feedback = runtime.feedback
        yield


async def _security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    # Swagger UI loads its assets from a CDN, so the strict policy would blank it.
    if not request.url.path.startswith(DOCS_URL):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    return response


def create_app(
    read: ReadServices | None = None, feedback: FeedbackServices | None = None
) -> FastAPI:
    app = FastAPI(
        title="ChatRadar",
        version=__version__,
        docs_url=DOCS_URL,
        redoc_url=None,
        lifespan=_real_services if read is None else None,
    )
    if read is not None:
        app.state.read = read
        app.state.feedback = feedback
    app.middleware("http")(write_guard)
    app.middleware("http")(_security_headers)

    @app.get("/healthz", tags=["service"])
    async def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.include_router(router)
    app.include_router(feedback_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
