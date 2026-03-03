import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import async_worker_runtime


@pytest.mark.anyio
async def test_init_worker_runtime_async_is_disabled() -> None:
    with pytest.raises(RuntimeError, match="arq app.arq_worker.WorkerSettings"):
        await async_worker_runtime.init_worker_runtime_async()


@pytest.mark.anyio
async def test_close_worker_runtime_async_is_disabled() -> None:
    with pytest.raises(RuntimeError, match="arq app.arq_worker.WorkerSettings"):
        await async_worker_runtime.close_worker_runtime_async()
