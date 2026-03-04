import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import storage
from app.config import settings
from app.infra import fs_runtime


class _Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    async def read(self) -> bytes:
        return self.payload


class _FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.deleted: list[tuple[str, str]] = []

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        _ = ContentType
        self.objects[(Bucket, Key)] = Body

    async def get_object(self, *, Bucket: str, Key: str):
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    async def delete_object(self, *, Bucket: str, Key: str):
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
        _ = ExpiresIn
        return f"https://signed/{Params['Bucket']}/{Params['Key']}"


@pytest.mark.anyio
async def test_patch_blob_s3_concurrent_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)

    try:
        settings.storage_backend = "s3"
        settings.s3_bucket = "bucket"

        payloads = [f"patch-{idx}" for idx in range(6)]
        metas = await asyncio.gather(
            *[storage.store_patch_blob_async(payload) for payload in payloads]
        )
        read_back = await asyncio.gather(*[storage.read_patch_blob_async(meta) for meta in metas])
        urls = await asyncio.gather(*[storage.get_patch_download_url_async(meta) for meta in metas])
        await asyncio.gather(*[storage.delete_patch_blob_async(meta) for meta in metas])

        assert read_back == payloads
        assert all(url and url.startswith("https://signed/bucket/") for url in urls)
        assert len(fake.deleted) == len(payloads)
    finally:
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_s3_signed_url_async_uses_storage_sdk_runtime_not_fs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeS3()
    fs_called = {"value": False}
    storage_runtime_called = {"value": False}
    cpu_called = {"value": False}

    async def _fake_run_fs_io_async(*_args, **_kwargs):
        fs_called["value"] = True
        raise AssertionError("run_fs_io_async must not be used for signed URL generation")

    async def _fake_run_storage_sdk_io_async(func, *args, **kwargs):
        storage_runtime_called["value"] = True
        return func(*args, **kwargs)

    async def _fake_run_cpu_io_async(*_args, **_kwargs):
        cpu_called["value"] = True
        raise AssertionError("run_cpu_io_async must not be used for signed URL generation")

    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "run_fs_io_async", _fake_run_fs_io_async)
    monkeypatch.setattr(storage, "run_storage_sdk_io_async", _fake_run_storage_sdk_io_async)
    monkeypatch.setattr(storage, "run_cpu_io_async", _fake_run_cpu_io_async, raising=False)

    url = await storage._s3_signed_url_async("bucket", "patches/a.diff")

    assert fs_called["value"] is False
    assert storage_runtime_called["value"] is True
    assert cpu_called["value"] is False
    assert url == "https://signed/bucket/patches/a.diff"


@pytest.mark.anyio
async def test_s3_signed_url_async_sdk_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket

    class _FailingS3(_FakeS3):
        def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
            _ = (Params, ExpiresIn)
            raise RuntimeError("sdk error")

    fake = _FailingS3()
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)

    try:
        settings.storage_backend = "s3"
        settings.s3_bucket = "bucket"

        meta = await storage.store_patch_blob_async("patch")
        assert "download_url" not in meta
        assert await storage.get_patch_download_url_async(meta) is None
    finally:
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_get_patch_download_url_async_does_not_use_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()

    async def _raise_cpu_runtime(*_args, **_kwargs):
        raise AssertionError("CPU runtime must not be used for download URL generation")

    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "run_cpu_io_async", _raise_cpu_runtime, raising=False)

    try:
        settings.storage_backend = "s3"
        settings.s3_bucket = "bucket"
        meta = await storage.store_patch_blob_async("patch")

        url = await storage.get_patch_download_url_async(meta)

        assert url == f"https://signed/{meta['bucket']}/{meta['key']}"
    finally:
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_s3_signed_url_async_respects_semaphore_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limit = 2
    current = 0
    max_seen = 0
    lock = threading.Lock()

    class _BlockingS3(_FakeS3):
        def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
            nonlocal current, max_seen
            _ = (_method, Params, ExpiresIn)
            with lock:
                current += 1
                max_seen = max(max_seen, current)
            time.sleep(0.05)
            with lock:
                current -= 1
            return "https://signed/bucket/key"

    fake = _BlockingS3()
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "_S3_SIGNED_URL_SEMAPHORE", asyncio.Semaphore(limit))
    monkeypatch.setattr(storage, "_S3_SIGNED_URL_SEMAPHORE_LOOP", asyncio.get_running_loop())

    urls = await asyncio.gather(
        *[storage._s3_signed_url_async("bucket", f"patches/{idx}.diff") for idx in range(8)]
    )

    assert all(url == "https://signed/bucket/key" for url in urls)
    assert max_seen <= limit


@pytest.mark.anyio
async def test_s3_signed_url_semaphore_reinit_after_loop_change_and_concurrency_kept() -> None:
    storage._S3_SIGNED_URL_SEMAPHORE = None
    storage._S3_SIGNED_URL_SEMAPHORE_LOOP = None

    sem_main = storage._get_s3_signed_url_semaphore()
    main_loop = asyncio.get_running_loop()

    thread_data: dict[str, object] = {}

    def _thread_runner() -> None:
        async def _run() -> None:
            sem_thread = storage._get_s3_signed_url_semaphore()
            thread_data["sem"] = sem_thread
            thread_data["loop"] = storage._S3_SIGNED_URL_SEMAPHORE_LOOP

        asyncio.run(_run())

    worker = threading.Thread(target=_thread_runner)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()

    sem_after = storage._get_s3_signed_url_semaphore()

    assert sem_main is not thread_data["sem"]
    assert thread_data["loop"] is not main_loop
    assert sem_after is not thread_data["sem"]
    assert storage._S3_SIGNED_URL_SEMAPHORE_LOOP is main_loop


@pytest.mark.anyio
async def test_presign_load_does_not_increase_fs_runtime_queue_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeS3()
    original_workers = settings.fs_runtime_max_workers
    original_concurrency = settings.fs_runtime_max_concurrency

    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)
    settings.fs_runtime_max_workers = 1
    settings.fs_runtime_max_concurrency = 1

    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    fs_tasks = 4
    presign_tasks = 16

    try:
        await asyncio.gather(
            *[
                storage._s3_signed_url_async("bucket", f"patches/{idx}.diff")
                for idx in range(presign_tasks)
            ],
            *[
                fs_runtime.run_fs_io_async(time.sleep, 0.03, operation="test.fs_load")
                for _ in range(fs_tasks)
            ],
        )

        runtime = fs_runtime._fs_runtime
        assert runtime is not None
        assert runtime.peak_queue_depth <= fs_tasks
    finally:
        await fs_runtime.close_fs_runtime()
        settings.fs_runtime_max_workers = original_workers
        settings.fs_runtime_max_concurrency = original_concurrency
