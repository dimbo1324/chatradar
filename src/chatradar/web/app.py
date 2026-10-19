from __future__ import annotations

import importlib
import inspect
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chatradar import __version__
from chatradar.config import get_settings
from chatradar.web.api import router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

    from chatradar.services.queries import ReadServices

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
    # Imported lazily: the container wires storage and is only needed outside tests.
    container = importlib.import_module("chatradar.services.container")
    built: Any = container.build_read_services(get_settings())
    if isinstance(built, AbstractAsyncContextManager):
        manager = cast("AbstractAsyncContextManager[ReadServices]", built)
        async with manager as read:
            app.state.read = read
            yield
        return
    if inspect.isawaitable(built):
        built = await built
    app.state.read = built
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


def create_app(read: ReadServices | None = None) -> FastAPI:
    app = FastAPI(
        title="ChatRadar",
        version=__version__,
        docs_url=DOCS_URL,
        redoc_url=None,
        lifespan=_real_services if read is None else None,
    )
    if read is not None:
        app.state.read = read
    app.middleware("http")(_security_headers)

    @app.get("/healthz", tags=["service"])
    async def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
