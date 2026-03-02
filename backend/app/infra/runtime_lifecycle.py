from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..config import settings


LifecycleStep = tuple[str, Callable[[], Awaitable[None]]]


def build_startup_steps(*, role: str) -> list[LifecycleStep]:
    from ..async_db import init_async_db
    from ..infra.cpu_runtime import init_cpu_runtime
    from ..infra.external_io_runtime import init_external_io_runtime
    from ..infra.fs_runtime import init_fs_runtime
    from ..infra.redis_client import init_redis_pool_async
    from ..llm.client import init_async_openai_client
    from ..s3_runtime import init_s3_runtime
    from ..infra.async_worker_runtime import init_worker_runtime_async

    if role == "worker":
        return [("init_worker_runtime_async", init_worker_runtime_async)]

    steps: list[LifecycleStep] = [
        ("init_redis_pool_async", init_redis_pool_async),
        ("init_async_db", init_async_db),
        ("init_fs_runtime", init_fs_runtime),
        ("init_cpu_runtime", init_cpu_runtime),
        ("init_external_io_runtime", init_external_io_runtime),
    ]


    if (settings.storage_backend or "local").strip().lower() == "s3":
        steps.append(("init_s3_runtime", init_s3_runtime))
    if settings.openai_api_key:
        steps.append(("init_async_openai_client", init_async_openai_client))

    _ = role
    return steps


def build_cleanup_steps(*, role: str) -> list[LifecycleStep]:
    from ..async_db import close_async_db
    from ..infra.cpu_runtime import close_cpu_runtime
    from ..infra.external_io_runtime import close_external_io_runtime
    from ..infra.fs_runtime import close_fs_runtime
    from ..infra.redis_client import close_redis_pool_async
    from ..llm.client import close_async_openai_client
    from ..s3_runtime import close_s3_runtime
    from ..scan import close_scan_runtime
    from ..infra.async_worker_runtime import close_worker_runtime_async

    if role == "worker":
        return [("close_worker_runtime_async", close_worker_runtime_async)]

    steps: list[LifecycleStep] = [
        ("close_s3_runtime", close_s3_runtime),
        ("close_redis_pool_async", close_redis_pool_async),
        ("close_async_openai_client", close_async_openai_client),
        ("close_fs_runtime", close_fs_runtime),
        ("close_cpu_runtime", close_cpu_runtime),
        ("close_external_io_runtime", close_external_io_runtime),
    ]
    if role == "api":
        steps.append(("close_scan_runtime", close_scan_runtime))
    steps.append(("close_async_db", close_async_db))
    return steps
