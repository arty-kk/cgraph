# backend/app/logging.py
from __future__ import annotations

import logging
import time
import uuid
from logging.config import dictConfig
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import Response


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def setup_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": (
                        "%(asctime)s [%(levelname)s] %(name)s — %(message)s "
                        "request_id=%(request_id)s"
                    ),
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "root": {
                "handlers": ["console"],
                "level": "INFO",
            },
            "filters": {
                "request_id": {
                    "()": RequestIdFilter,
                }
            },
            "disable_existing_loggers": False,
        }
    )


def get_logger(name: str = "stubgraph") -> logging.Logger:
    return logging.getLogger(name)


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    request_id = (request.headers.get("x-request-id") or "").strip() or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    duration_ms = (time.perf_counter() - started) * 1000
    logger = get_logger("stubgraph.api")
    logger.info(
        "HTTP %s %s",
        request.method,
        request.url.path,
        extra={
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "request_id": request_id,
        },
    )
    return response
