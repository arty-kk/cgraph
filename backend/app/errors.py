# backend/app/errors.py
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

LOGGER = logging.getLogger("stubgraph.api")


class AppError(Exception):
    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | HTTPStatus | None = None,
        code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code or self.status_code)
        self.code = code or self.code
        self.context = context or {}


class BadRequestError(AppError):
    code = "bad_request"
    status_code = HTTPStatus.BAD_REQUEST


class NotFoundError(AppError):
    code = "not_found"
    status_code = HTTPStatus.NOT_FOUND


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = HTTPStatus.UNAUTHORIZED


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = HTTPStatus.FORBIDDEN


class LimitExceededError(AppError):
    code = "limit_exceeded"
    status_code = HTTPStatus.BAD_REQUEST


class ExternalServiceError(AppError):
    code = "external_service_error"
    status_code = HTTPStatus.BAD_GATEWAY


class PathValidationError(BadRequestError, ValueError):
    code = "invalid_path"


class ServerError(AppError):
    code = "server_error"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR


def _safe_context(context: dict[str, Any]) -> dict[str, Any]:
    safe_ctx: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, (str, int, float, bool)):
            safe_ctx[key] = value
        else:
            safe_ctx[key] = repr(value)
    return safe_ctx


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    payload = {
        "error": {
            "code": exc.code,
            "message": exc.message,
        }
    }
    if exc.context:
        payload["error"]["context"] = _safe_context(exc.context)

    LOGGER.warning(
        "Request failed",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status": exc.status_code,
            "error_code": exc.code,
            **_safe_context(exc.context),
        },
    )
    return JSONResponse(status_code=exc.status_code, content=payload)


async def _handle_unexpected_error(request: Request, exc: Exception) -> Response:
    LOGGER.exception(
        "Unexpected error",
        extra={"path": request.url.path, "method": request.method},
    )
    payload = {
        "error": {
            "code": ServerError.code,
            "message": "Внутренняя ошибка сервера",
        }
    }
    return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content=payload)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)


HttpMiddleware = Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]
