import asyncio
import builtins
import io
import sys
import threading
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import snapshots
from app.config import settings
from app.errors import BadRequestError


class _Upload:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0
        self.seek_calls: list[int] = []

    async def seek(self, offset: int):
        self.seek_calls.append(offset)
        self._offset = offset

    async def read(self, size: int = -1):
        if size <= 0:
            size = len(self._data) - self._offset
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _ChunkedUpload(_Upload):
    def __init__(self, data: bytes, chunk_size: int):
        super().__init__(data)
        self._chunk_size = max(1, int(chunk_size))

    async def read(self, size: int = -1):
        _ = size
        if self._offset >= len(self._data):
            return b""
        chunk = self._data[self._offset : self._offset + self._chunk_size]
        self._offset += len(chunk)
        return chunk


class _AsyncBody:
    def __init__(self, payload: bytes, fail_after_first: bool = False):
        self._payload = payload
        self._offset = 0
        self._fail_after_first = fail_after_first
        self.closed = False

    async def read(self, size: int):
        if self._fail_after_first and self._offset > 0:
            raise RuntimeError("stream broken")
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


class _FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.multipart: dict[str, dict[int, bytes]] = {}
        self.upload_targets: dict[str, tuple[str, str]] = {}
        self.deleted: list[tuple[str, str]] = []
        self._upload_counter = 0
        self._active_upload_parts = 0
        self.max_active_upload_parts = 0

    async def get_object(self, *, Bucket: str, Key: str):
        return {"Body": _AsyncBody(self.objects[(Bucket, Key)])}

    async def create_multipart_upload(self, *, Bucket: str, Key: str):
        self._upload_counter += 1
        upload_id = f"u-{self._upload_counter}"
        self.multipart[upload_id] = {}
        self.upload_targets[upload_id] = (Bucket, Key)
        return {"UploadId": upload_id}

    async def upload_part(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        PartNumber: int,
        Body: bytes,
    ):
        assert self.upload_targets[UploadId] == (Bucket, Key)
        self._active_upload_parts += 1
        self.max_active_upload_parts = max(self.max_active_upload_parts, self._active_upload_parts)
        try:
            await asyncio.sleep(0.01)
            self.multipart[UploadId][PartNumber] = Body
            return {"ETag": f"etag-{PartNumber}"}
        finally:
            self._active_upload_parts = max(0, self._active_upload_parts - 1)

    async def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict,
    ):
        _ = MultipartUpload
        parts = self.multipart.pop(UploadId)
        data = b"".join(parts[idx] for idx in sorted(parts))
        self.objects[(Bucket, Key)] = data

    async def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str):
        _ = Bucket, Key
        self.multipart.pop(UploadId, None)

    async def delete_object(self, *, Bucket: str, Key: str):
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)


def _multipart_payload(parts: int) -> bytes:
    return (b"12345678" * 1024 * 1024)[: 8 * 1024 * 1024] * max(1, parts)


def _zip_payload(content: str = "hello") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("repo/README.md", content)
    return buffer.getvalue()


@pytest.mark.anyio
async def test_store_snapshot_upload_reads_async_stream() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            upload = _Upload(_zip_payload())
            meta = await snapshots.store_snapshot_upload(upload, "repo.zip")
            root = await snapshots.prepare_snapshot_root_async(meta)

            assert upload.seek_calls == [0]
            assert (root / "repo" / "README.md").exists()
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend


@pytest.mark.anyio
async def test_store_snapshot_upload_enforces_limit() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_limit = settings.snapshot_max_bytes
    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"
            settings.snapshot_max_bytes = 20

            upload = _Upload(_zip_payload("hello world"))
            with pytest.raises(BadRequestError, match="Архив слишком большой"):
                await snapshots.store_snapshot_upload(upload, "repo.zip")
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.snapshot_max_bytes = original_limit


@pytest.mark.anyio
async def test_store_snapshot_upload_rejects_empty_payload() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            upload = _Upload(b"")
            with pytest.raises(BadRequestError, match="Архив пустой"):
                await snapshots.store_snapshot_upload(upload, "repo.zip")
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend


@pytest.mark.anyio
async def test_store_snapshot_upload_buffers_chunk_writes() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            payload = _zip_payload("hello" * 2000)
            upload = _ChunkedUpload(payload, chunk_size=128)
            meta = await snapshots.store_snapshot_upload(upload, "repo.zip")

            assert meta.size == len(payload)
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend


@pytest.mark.anyio
async def test_download_snapshot_archive_from_s3_streams_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeS3()
    fake.objects[("bucket", "snapshots/sha/repo.zip")] = b"abcdef"
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    meta = snapshots.SnapshotMeta(
        storage="s3",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=6,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
        bucket="bucket",
        key="snapshots/sha/repo.zip",
    )
    out = tmp_path / "archive.zip"

    await snapshots._download_snapshot_archive_from_s3(meta, out)

    assert out.read_bytes() == b"abcdef"


@pytest.mark.anyio
async def test_download_snapshot_archive_from_s3_cleans_partial_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _AsyncBody(b"abcdef", fail_after_first=True)

    class _BrokenS3:
        async def get_object(self, *, Bucket: str, Key: str):
            _ = Bucket, Key
            return {"Body": body}

    monkeypatch.setattr(snapshots, "get_s3_client", lambda: _BrokenS3())

    meta = snapshots.SnapshotMeta(
        storage="s3",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=6,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
        bucket="bucket",
        key="snapshots/sha/repo.zip",
    )
    out = tmp_path / "archive.zip"

    with pytest.raises(RuntimeError, match="stream broken"):
        await snapshots._download_snapshot_archive_from_s3(meta, out)

    assert body.closed is True
    assert not out.exists()


@pytest.mark.anyio
async def test_download_snapshot_archive_from_s3_respects_concurrency_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TrackingBody:
        def __init__(self, payload: bytes, state: dict[str, int]):
            self._payload = payload
            self._offset = 0
            self._state = state

        async def read(self, size: int):
            self._state["active"] += 1
            self._state["max_active"] = max(self._state["max_active"], self._state["active"])
            try:
                await asyncio.sleep(0.01)
                chunk = self._payload[self._offset : self._offset + size]
                self._offset += len(chunk)
                return chunk
            finally:
                self._state["active"] = max(0, self._state["active"] - 1)

        async def close(self) -> None:
            return None

    state = {"active": 0, "max_active": 0}

    class _TrackingS3:
        async def get_object(self, *, Bucket: str, Key: str):
            _ = Bucket, Key
            return {"Body": _TrackingBody(b"abcdef", state)}

    monkeypatch.setattr(snapshots, "get_s3_client", lambda: _TrackingS3())

    original_limit = settings.snapshot_s3_concurrency
    settings.snapshot_s3_concurrency = 1
    snapshots._SNAPSHOT_S3_IO_SEMAPHORE = None
    snapshots._SNAPSHOT_S3_IO_SEMAPHORE_LOOP = None

    meta = snapshots.SnapshotMeta(
        storage="s3",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=6,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
        bucket="bucket",
        key="snapshots/sha/repo.zip",
    )
    out_a = tmp_path / "archive-a.zip"
    out_b = tmp_path / "archive-b.zip"

    try:
        await asyncio.gather(
            snapshots._download_snapshot_archive_from_s3(meta, out_a),
            snapshots._download_snapshot_archive_from_s3(meta, out_b),
        )
    finally:
        settings.snapshot_s3_concurrency = original_limit

    assert state["max_active"] <= 1
    assert out_a.read_bytes() == b"abcdef"
    assert out_b.read_bytes() == b"abcdef"


def test_get_snapshot_s3_io_semaphore_recreated_for_new_event_loop() -> None:
    snapshots._SNAPSHOT_S3_IO_SEMAPHORE = None
    snapshots._SNAPSHOT_S3_IO_SEMAPHORE_LOOP = None
    snapshots._SNAPSHOT_S3_IO_SEMAPHORE_LOCK = None
    snapshots._SNAPSHOT_S3_IO_SEMAPHORE_LOCK_LOOP = None

    semaphores: list[asyncio.Semaphore] = []
    semaphores_lock = threading.Lock()
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def _worker() -> None:
        try:
            semaphore = asyncio.run(snapshots._get_snapshot_s3_io_semaphore())
            with semaphores_lock:
                semaphores.append(semaphore)
        except BaseException as exc:  # noqa: BLE001
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(semaphores) == 2
    assert semaphores[0] is not semaphores[1]


@pytest.mark.anyio
async def test_snapshot_s3_concurrent_upload_download_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    original_s3_concurrency = settings.snapshot_s3_concurrency
    fake = _FakeS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "s3"
            settings.s3_bucket = "bucket"
            settings.snapshot_s3_concurrency = 2
            snapshots._SNAPSHOT_S3_IO_SEMAPHORE = None
            snapshots._SNAPSHOT_S3_IO_SEMAPHORE_LOOP = None

            uploads = [_Upload(_zip_payload(f"content-{idx}")) for idx in range(4)]
            metas = await asyncio.gather(
                *[
                    snapshots.store_snapshot_upload(upload, f"repo-{idx}.zip")
                    for idx, upload in enumerate(uploads)
                ]
            )

            roots = await asyncio.gather(
                *[snapshots.prepare_snapshot_root_async(meta) for meta in metas]
            )
            for idx, root in enumerate(roots):
                assert (root / "repo" / "README.md").read_text(encoding="utf-8") == f"content-{idx}"

            await asyncio.gather(*[snapshots.delete_snapshot_async(meta) for meta in metas])
            assert len(fake.deleted) == len(metas)
            assert fake.max_active_upload_parts <= settings.snapshot_s3_concurrency
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket
        settings.snapshot_s3_concurrency = original_s3_concurrency


@pytest.mark.anyio
async def test_snapshot_fs_ops_use_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend

    operations: list[str] = []
    lanes: list[str] = []

    async def _fake_run_fs_io_async(fn, *args, operation=None, lane="interactive", **kwargs):
        operations.append(operation or "")
        lanes.append(lane)
        return fn(*args, **kwargs)

    async def _forbid_to_thread(*_args, **_kwargs):
        raise AssertionError("snapshots should use run_fs_io_async instead of asyncio.to_thread")

    monkeypatch.setattr(snapshots, "run_fs_io_async", _fake_run_fs_io_async)
    monkeypatch.setattr(snapshots.asyncio, "to_thread", _forbid_to_thread)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            meta = await snapshots.store_snapshot_upload(
                _Upload(_zip_payload("runtime")),
                "repo.zip",
            )
            root = await snapshots.prepare_snapshot_root_async(meta)
            assert (root / "repo" / "README.md").read_text(encoding="utf-8") == "runtime"
            await snapshots.delete_snapshot_async(meta)
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend

    assert "snapshots.tmp.mkdir" in operations
    assert "snapshots.archive.append_chunks" in operations
    assert "snapshots.extract.archive" in operations
    assert "snapshots.dir.clear_rmdir" in operations
    assert lanes and set(lanes) == {"bulk"}


@pytest.mark.anyio
async def test_store_snapshot_upload_aborts_multipart_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket

    class _BrokenS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.abort_calls = 0

        async def upload_part(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            PartNumber: int,
            Body: bytes,
        ):
            _ = Bucket, Key, UploadId, Body
            if PartNumber == 1:
                raise RuntimeError("upload failed")
            return await super().upload_part(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                Body=Body,
            )

        async def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str):
            self.abort_calls += 1
            await super().abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=UploadId)

    broken = _BrokenS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: broken)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "s3"
            settings.s3_bucket = "bucket"

            with pytest.raises(snapshots.SnapshotError, match="Failed to upload snapshot to S3"):
                await snapshots.store_snapshot_upload(_Upload(_zip_payload("err")), "repo.zip")
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket

    assert broken.abort_calls == 1


@pytest.mark.anyio
async def test_snapshot_parallel_mixed_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    async def _pipeline(idx: int) -> None:
        meta = await snapshots.store_snapshot_upload(
            _Upload(_zip_payload(f"mix-{idx}")),
            f"repo-{idx}.zip",
        )
        root = await snapshots.prepare_snapshot_root_async(meta)
        assert (root / "repo" / "README.md").read_text(encoding="utf-8") == f"mix-{idx}"
        await snapshots.delete_snapshot_async(meta)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "s3"
            settings.s3_bucket = "bucket"

            await asyncio.gather(*[_pipeline(idx) for idx in range(6)])
            assert len(fake.deleted) == 6
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_snapshot_backpressure_stress_parallel_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    async def _pipeline(idx: int) -> None:
        meta = await snapshots.store_snapshot_upload(
            _Upload(_zip_payload(f"stress-{idx}")),
            f"repo-{idx}.zip",
        )
        archive_path = Path(settings.db_dir) / meta.file
        archive_path.unlink(missing_ok=True)

        root = await snapshots.prepare_snapshot_root_async(meta)
        assert (root / "repo" / "README.md").read_text(encoding="utf-8") == f"stress-{idx}"
        await snapshots.delete_snapshot_async(meta)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "s3"
            settings.s3_bucket = "bucket"

            await asyncio.gather(*[_pipeline(idx) for idx in range(12)])

            tmp_files = list((Path(tmpdir) / "snapshots" / "tmp").glob("*"))
            assert tmp_files == []
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_upload_archive_to_s3_bounded_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_concurrency = settings.snapshot_s3_concurrency

    class _SlowS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.in_flight = 0
            self.max_in_flight = 0

        async def upload_part(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            PartNumber: int,
            Body: bytes,
        ):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(0.03)
                return await super().upload_part(
                    Bucket=Bucket,
                    Key=Key,
                    UploadId=UploadId,
                    PartNumber=PartNumber,
                    Body=Body,
                )
            finally:
                self.in_flight -= 1

    fake = _SlowS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    try:
        settings.snapshot_s3_concurrency = 2
        archive_path = tmp_path / "big.bin"
        archive_path.write_bytes(_multipart_payload(parts=5))

        await snapshots._upload_archive_to_s3(archive_path, "bucket", "snapshots/sha/big.bin")
    finally:
        settings.snapshot_s3_concurrency = original_concurrency

    assert fake.max_in_flight <= 2
    assert fake.max_in_flight >= 1


@pytest.mark.anyio
async def test_upload_archive_to_s3_validates_and_sorts_parts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _OutOfOrderS3(_FakeS3):
        async def upload_part(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            PartNumber: int,
            Body: bytes,
        ):
            await asyncio.sleep(0.03 if PartNumber % 2 == 0 else 0.0)
            return await super().upload_part(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                Body=Body,
            )

        async def complete_multipart_upload(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            MultipartUpload: dict,
        ):
            parts = MultipartUpload["Parts"]
            assert parts
            assert [part["PartNumber"] for part in parts] == list(range(1, len(parts) + 1))
            assert len({part["PartNumber"] for part in parts}) == len(parts)
            await super().complete_multipart_upload(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                MultipartUpload=MultipartUpload,
            )

    fake = _OutOfOrderS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    archive_path = tmp_path / "ordered.bin"
    archive_path.write_bytes(_multipart_payload(parts=4))

    await snapshots._upload_archive_to_s3(archive_path, "bucket", "snapshots/sha/ordered.bin")


@pytest.mark.anyio
async def test_upload_archive_to_s3_cancellation_aborts_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _BlockingS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.abort_calls = 0
            self.started = asyncio.Event()

        async def upload_part(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            PartNumber: int,
            Body: bytes,
        ):
            _ = Bucket, Key, UploadId, PartNumber, Body
            self.started.set()
            await asyncio.sleep(1)
            return {"ETag": "etag"}

        async def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str):
            self.abort_calls += 1
            await super().abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=UploadId)

    fake = _BlockingS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    archive_path = tmp_path / "cancel.bin"
    archive_path.write_bytes(_multipart_payload(parts=2))

    task = asyncio.create_task(
        snapshots._upload_archive_to_s3(
            archive_path,
            "bucket",
            "snapshots/sha/cancel.bin",
        )
    )
    await fake.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0)
    worker_tasks = [
        pending
        for pending in asyncio.all_tasks()
        if pending is not asyncio.current_task()
        and pending.get_coro().__name__ == "_upload_worker"
        and not pending.done()
    ]

    assert fake.abort_calls == 1
    assert worker_tasks == []




@pytest.mark.anyio
async def test_upload_archive_to_s3_uses_runtime_open_read_close_ops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operations: list[str] = []
    lanes: list[str] = []
    opened_streams: list[io.BufferedReader] = []
    open_helper_calls = 0

    original_run_fs_io_async = snapshots.run_fs_io_async

    def _tracking_open_archive_read_stream(archive_path: Path):
        nonlocal open_helper_calls
        open_helper_calls += 1
        stream = builtins.open(archive_path, "rb")
        opened_streams.append(stream)
        return stream

    def _forbid_path_open(self: Path, *_args, **_kwargs):
        raise AssertionError("direct Path.open usage is forbidden in upload hot-path")

    async def _tracking_run_fs_io_async(fn, *args, operation=None, lane="interactive", **kwargs):
        operations.append(operation or "")
        lanes.append(lane)
        return await original_run_fs_io_async(fn, *args, operation=operation, lane=lane, **kwargs)

    archive_path = tmp_path / "hot-path.bin"
    archive_path.write_bytes(_multipart_payload(parts=3))

    fake = _FakeS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)
    monkeypatch.setattr(Path, "open", _forbid_path_open)
    monkeypatch.setattr(snapshots, "_open_archive_read_stream", _tracking_open_archive_read_stream)
    monkeypatch.setattr(snapshots, "run_fs_io_async", _tracking_run_fs_io_async)

    await snapshots._upload_archive_to_s3(archive_path, "bucket", "snapshots/sha/hot-path.bin")

    assert "snapshots.archive.open_read_stream" in operations
    assert "snapshots.archive.read_chunks" in operations
    assert "snapshots.archive.close_read_stream" in operations
    assert operations.count("snapshots.archive.open_read_stream") == 1
    assert operations.count("snapshots.archive.close_read_stream") == 1
    assert lanes and set(lanes) == {"bulk"}
    assert open_helper_calls == 1
    assert opened_streams and all(stream.closed for stream in opened_streams)
    assert lanes and set(lanes) == {"bulk"}

@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["error", "cancel"])
async def test_upload_archive_to_s3_closes_stream_on_failure_or_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    operations: list[str] = []
    lanes: list[str] = []
    opened_streams: list[io.BufferedReader] = []

    original_run_fs_io_async = snapshots.run_fs_io_async

    async def _tracking_run_fs_io_async(fn, *args, operation=None, lane="interactive", **kwargs):
        operations.append(operation or "")
        lanes.append(lane)
        result = await original_run_fs_io_async(fn, *args, operation=operation, lane=lane, **kwargs)
        if operation == "snapshots.archive.open_read_stream":
            opened_streams.append(result)
        return result

    monkeypatch.setattr(snapshots, "run_fs_io_async", _tracking_run_fs_io_async)

    class _FailureS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()

        async def upload_part(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            PartNumber: int,
            Body: bytes,
        ):
            _ = Bucket, Key, UploadId, PartNumber, Body
            self.started.set()
            if mode == "error":
                raise RuntimeError("transient")
            await asyncio.sleep(1)
            return {"ETag": "etag"}

    fake = _FailureS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    archive_path = tmp_path / f"fd-{mode}.bin"
    archive_path.write_bytes(_multipart_payload(parts=2))

    if mode == "error":
        with pytest.raises(RuntimeError, match="transient"):
            await snapshots._upload_archive_to_s3(
                archive_path,
                "bucket",
                f"snapshots/sha/fd-{mode}.bin",
            )
    else:
        task = asyncio.create_task(
            snapshots._upload_archive_to_s3(
                archive_path,
                "bucket",
                f"snapshots/sha/fd-{mode}.bin",
            )
        )
        await fake.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    renamed_path = archive_path.with_suffix(".moved")
    archive_path.rename(renamed_path)
    renamed_path.unlink()

    assert "snapshots.archive.open_read_stream" in operations
    assert "snapshots.archive.read_chunks" in operations
    assert "snapshots.archive.close_read_stream" in operations
    assert operations.count("snapshots.archive.open_read_stream") == 1
    assert operations.count("snapshots.archive.close_read_stream") == 1
    assert opened_streams and all(stream.closed for stream in opened_streams)


@pytest.mark.anyio
async def test_snapshot_parallel_pipeline_with_retry_and_no_hanging_multipart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket

    class _TransientS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.failures: dict[str, int] = {}

        async def upload_part(
            self,
            *,
            Bucket: str,
            Key: str,
            UploadId: str,
            PartNumber: int,
            Body: bytes,
        ):
            await asyncio.sleep(0.01)
            fail_key = f"{Bucket}/{Key}"
            if PartNumber == 1 and self.failures.get(fail_key, 0) == 0:
                self.failures[fail_key] = 1
                raise RuntimeError("temporary")
            return await super().upload_part(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                Body=Body,
            )

    fake = _TransientS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    async def _pipeline(idx: int) -> None:
        payload = _zip_payload(f"retry-{idx}-" + ("x" * 1_000_000))
        upload = _Upload(payload)
        archive_name = f"repo-{idx}.zip"
        try:
            await snapshots.store_snapshot_upload(upload, archive_name)
        except snapshots.SnapshotError:
            upload = _Upload(payload)
        meta = await snapshots.store_snapshot_upload(upload, archive_name)
        archive_path = Path(settings.db_dir) / meta.file
        archive_path.unlink(missing_ok=True)
        root = await snapshots.prepare_snapshot_root_async(meta)
        assert (root / "repo" / "README.md").read_text(encoding="utf-8").startswith(f"retry-{idx}-")
        await snapshots.delete_snapshot_async(meta)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "s3"
            settings.s3_bucket = "bucket"

            await asyncio.gather(*[_pipeline(idx) for idx in range(4)])
            assert fake.multipart == {}
            assert list((Path(tmpdir) / "snapshots" / "tmp").glob("*")) == []

            class _AlwaysFailS3(_FakeS3):
                def __init__(self):
                    super().__init__()
                    self.abort_calls = 0
                    self.started = asyncio.Event()

                async def upload_part(
                    self,
                    *,
                    Bucket: str,
                    Key: str,
                    UploadId: str,
                    PartNumber: int,
                    Body: bytes,
                ):
                    _ = Bucket, Key, UploadId, PartNumber, Body
                    self.started.set()
                    raise RuntimeError("forced multipart failure")

                async def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str):
                    self.abort_calls += 1
                    await super().abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=UploadId)

            failing = _AlwaysFailS3()
            monkeypatch.setattr(snapshots, "get_s3_client", lambda: failing)

            failed_archive = Path(tmpdir) / "snapshots" / "failed.bin"
            failed_archive.parent.mkdir(parents=True, exist_ok=True)
            failed_archive.write_bytes(_multipart_payload(parts=2))

            with pytest.raises(RuntimeError, match="forced multipart failure"):
                await snapshots._upload_archive_to_s3(
                    failed_archive,
                    "bucket",
                    "snapshots/sha/failed.bin",
                )

            await asyncio.sleep(0)
            worker_tasks = [
                pending
                for pending in asyncio.all_tasks()
                if pending is not asyncio.current_task()
                and pending.get_coro().__name__ == "_upload_worker"
                and not pending.done()
            ]

            assert failing.abort_calls == 1
            assert failing.multipart == {}
            assert worker_tasks == []
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket
