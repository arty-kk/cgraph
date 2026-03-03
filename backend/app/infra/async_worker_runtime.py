from __future__ import annotations

_RUNTIME_ERROR_MESSAGE = (
    "Legacy async worker runtime is disabled. "
    "Start workers only with `arq app.arq_worker.WorkerSettings`."
)


async def init_worker_runtime_async() -> None:
    raise RuntimeError(_RUNTIME_ERROR_MESSAGE)


async def close_worker_runtime_async() -> None:
    raise RuntimeError(_RUNTIME_ERROR_MESSAGE)
