import asyncio
import io
import sys
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

    async def get_object(self, *, Bucket: str, Key: str):
        return {"Body": _AsyncBody(self.objects[(Bucket, Key)])}

    async def create_multipart_upload(self, *, Bucket: str, Key: str):
        self._upload_counter += 1
        upload_id = f"u-{self._upload_counter}"
        self.multipart[upload_id] = {}
        self.upload_targets[upload_id] = (Bucket, Key)
        return {"UploadId": upload_id}

    async def upload_part(self, *, Bucket: str, Key: str, UploadId: str, PartNumber: int, Body: bytes):
        assert self.upload_targets[UploadId] == (Bucket, Key)
        self.multipart[UploadId][PartNumber] = Body
        return {"ETag": f"etag-{PartNumber}"}

    async def complete_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict):
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
async def test_download_snapshot_archive_from_s3_streams_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
async def test_snapshot_s3_concurrent_upload_download_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "s3"
            settings.s3_bucket = "bucket"

            uploads = [_Upload(_zip_payload(f"content-{idx}")) for idx in range(4)]
            metas = await asyncio.gather(
                *[snapshots.store_snapshot_upload(upload, f"repo-{idx}.zip") for idx, upload in enumerate(uploads)]
            )

            roots = await asyncio.gather(*[snapshots.prepare_snapshot_root_async(meta) for meta in metas])
            for idx, root in enumerate(roots):
                assert (root / "repo" / "README.md").read_text(encoding="utf-8") == f"content-{idx}"

            await asyncio.gather(*[snapshots.delete_snapshot_async(meta) for meta in metas])
            assert len(fake.deleted) == len(metas)
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_snapshot_fs_ops_use_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend

    operations: list[str] = []

    async def _fake_run_fs_io_async(fn, *args, operation=None, **kwargs):
        operations.append(operation or "")
        return fn(*args, **kwargs)

    async def _forbid_to_thread(*_args, **_kwargs):
        raise AssertionError("snapshots should use run_fs_io_async instead of asyncio.to_thread")

    monkeypatch.setattr(snapshots, "run_fs_io_async", _fake_run_fs_io_async)
    monkeypatch.setattr(snapshots.asyncio, "to_thread", _forbid_to_thread)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            meta = await snapshots.store_snapshot_upload(_Upload(_zip_payload("runtime")), "repo.zip")
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


@pytest.mark.anyio
async def test_store_snapshot_upload_aborts_multipart_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket

    class _BrokenS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.abort_calls = 0

        async def upload_part(self, *, Bucket: str, Key: str, UploadId: str, PartNumber: int, Body: bytes):
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
        meta = await snapshots.store_snapshot_upload(_Upload(_zip_payload(f"mix-{idx}")), f"repo-{idx}.zip")
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
async def test_snapshot_backpressure_stress_parallel_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()
    monkeypatch.setattr(snapshots, "get_s3_client", lambda: fake)

    async def _pipeline(idx: int) -> None:
        meta = await snapshots.store_snapshot_upload(_Upload(_zip_payload(f"stress-{idx}")), f"repo-{idx}.zip")
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
