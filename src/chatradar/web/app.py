from __future__ import annotations

from fastapi import FastAPI

from chatradar import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="ChatRadar", version=__version__, docs_url="/api/docs", redoc_url=None)

    @app.get("/healthz", tags=["service"])
    async def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "version": __version__}

    return app
