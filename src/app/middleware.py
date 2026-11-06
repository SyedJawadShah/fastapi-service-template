"""HTTP middleware: request IDs, request logging and security headers."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

log = logging.getLogger("app.request")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
HSTS = "max-age=31536000; includeSubDomains"
# Interactive API docs load assets from a CDN; they are only served outside production.
_CSP_EXEMPT_PATHS = frozenset({"/docs"})


def apply_security_headers(response: Response, path: str, *, hsts: bool) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if path not in _CSP_EXEMPT_PATHS:
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("Cache-Control", "no-store")
    if hsts:
        response.headers.setdefault("Strict-Transport-Security", HSTS)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        apply_security_headers(response, request.url.path, hsts=self.hsts)
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID and log one line per request, without query strings or bodies."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            route = request.scope.get("route")
            log.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    # The route template ("/items/{item_id}"), not the raw path, so
                    # identifiers in URLs stay out of the logs.
                    "route": getattr(route, "path", "unmatched"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
        response.headers["X-Request-ID"] = request_id
        return response
