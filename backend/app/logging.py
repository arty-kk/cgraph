#backend/app/logging.py
from __future__ import annotations

import logging
import time
from logging.config import dictConfig
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import Response


def setup_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {
                "handlers": ["console"],
                "level": "INFO",
            },
            "disable_existing_loggers": False,
        }
    )


def get_logger(name: str = "cgraph") -> logging.Logger:
    return logging.getLogger(name)


async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    logger = get_logger("cgraph.api")
    logger.info(
        "HTTP %s %s",
        request.method,
        request.url.path,
        extra={
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response
