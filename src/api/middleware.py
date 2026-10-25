"""
Middleware de seguridad — headers HTTP, logging estructurado y manejo de errores.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega headers de seguridad a todas las respuestas."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Solo para HTTPS (el reverse proxy lo aplica en producción)
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logging estructurado por request con request_id único."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # No logear el body de webhooks (puede contener datos sensibles)
        logger.info(
            "→ %s %s [%s] ip=%s",
            request.method,
            request.url.path,
            request_id,
            request.client.host if request.client else "unknown",
        )

        response = await call_next(request)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "← %s %s [%s] status=%d %dms",
            request.method,
            request.url.path,
            request_id,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-Id"] = request_id
        return response


class ErrorSanitizingMiddleware(BaseHTTPMiddleware):
    """Captura excepciones no manejadas y devuelve error genérico sin stack trace."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled error en %s: %s", request.url.path, exc)
            return JSONResponse(
                status_code=500,
                content={"detail": "Error interno del servidor"},
            )
