"""Application factory and ASGI entry point (`uvicorn app.main:app`)."""

import html
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app import health
from app.logging_setup import configure_logging
from app.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    apply_security_headers,
)
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.git_sha,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    # Starlette runs the last-added middleware first.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.error(
            "unhandled_error",
            exc_info=exc,
            extra={"request_id": request_id, "exc_type": type(exc).__name__},
        )
        response = JSONResponse(
            {"error": "internal_error", "request_id": request_id}, status_code=500
        )
        if request_id:
            response.headers["X-Request-ID"] = request_id
        apply_security_headers(response, request.url.path, hsts=settings.is_production)
        return response

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        name = html.escape(settings.app_name)
        version = html.escape(settings.git_sha)
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>{name}</title></head>"
            f"<body><h1>{name}</h1><p>Version {version}</p></body></html>"
        )

    return app


app = create_app()
