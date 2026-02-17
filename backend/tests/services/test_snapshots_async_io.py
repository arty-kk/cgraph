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
async def test_store_snapshot_upload_offloads_chunk_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    calls: list[int] = []

    original_append = snapshots._append_file_chunk

    def _tracking_append(path: Path, chunk: bytes) -> None:
        calls.append(len(chunk))
        original_append(path, chunk)

    monkeypatch.setattr(snapshots, "_append_file_chunk", _tracking_append)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            upload = _Upload(_zip_payload())
            meta = await snapshots.store_snapshot_upload(upload, "repo.zip")
            root = await snapshots.prepare_snapshot_root_async(meta)

            assert calls
            assert (root / "repo" / "README.md").exists()
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend




@pytest.mark.anyio
async def test_store_snapshot_upload_buffers_chunk_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    calls: list[int] = []

    original_append = snapshots._append_file_chunk

    def _tracking_append(path: Path, chunk: bytes) -> None:
        calls.append(len(chunk))
        original_append(path, chunk)

    monkeypatch.setattr(snapshots, "_append_file_chunk", _tracking_append)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            payload = _zip_payload("hello" * 2000)
            upload = _ChunkedUpload(payload, chunk_size=128)
            meta = await snapshots.store_snapshot_upload(upload, "repo.zip")

            assert meta.size == len(payload)
            assert calls
            assert len(calls) == 1
            assert calls[0] == len(payload)
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend




@pytest.mark.anyio
async def test_store_snapshot_upload_uses_archive_needs_update_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    called = {"value": False}

    original_helper = snapshots._archive_needs_update

    def _tracking_helper(archive_path: Path, expected_size: int, expected_sha: str) -> bool:
        called["value"] = True
        return original_helper(archive_path, expected_size, expected_sha)

    monkeypatch.setattr(snapshots, "_archive_needs_update", _tracking_helper)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            payload = _zip_payload("same")
            upload1 = _Upload(payload)
            upload2 = _Upload(payload)

            await snapshots.store_snapshot_upload(upload1, "repo.zip")
            await snapshots.store_snapshot_upload(upload2, "repo.zip")

            assert called["value"] is True
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend



@pytest.mark.anyio
async def test_store_snapshot_upload_uses_finalize_local_archive_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    called = {"value": False}

    original_helper = snapshots._finalize_local_archive

    def _tracking_helper(
        tmp_path: Path,
        archive_path: Path,
        expected_size: int,
        expected_sha: str,
    ) -> None:
        called["value"] = True
        original_helper(tmp_path, archive_path, expected_size, expected_sha)

    monkeypatch.setattr(snapshots, "_finalize_local_archive", _tracking_helper)

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            payload = _zip_payload("helper")
            upload = _Upload(payload)

            await snapshots.store_snapshot_upload(upload, "repo.zip")

            assert called["value"] is True
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend



@pytest.mark.anyio
async def test_prepare_snapshot_root_async_uses_archive_ensure_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    meta = snapshots.SnapshotMeta(
        storage="local",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
    )

    async def _fake_to_thread(func, *args, **kwargs):
        _ = kwargs
        name = getattr(func, "__name__", "")
        calls.append(name)
        if name == "_resolve_root_and_get_state":
            return Path("/tmp/repo"), Path("/tmp/repo/.extracted_ok"), False, False
        return None

    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    await snapshots.prepare_snapshot_root_async(meta)

    assert "_resolve_root_and_get_state" in calls
    assert "_ensure_archive_and_extract" in calls

@pytest.mark.anyio
async def test_snapshot_async_helpers_use_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, tuple, dict]] = []
    prepare_meta = snapshots.SnapshotMeta(
        storage="local",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
    )

    async def _fake_prepare_snapshot_root_async(meta):
        assert meta is prepare_meta
        return Path("/tmp/shared-repo")

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        if getattr(func, "__name__", "") in {"_resolve_path", "resolve"}:
            return Path("/tmp/project-repo")
        if getattr(func, "__name__", "") == "_resolve_path_and_dir_state":
            return Path("/tmp/project-repo"), True, True
        if getattr(func, "__name__", "") == "_path_exists_and_is_dir":
            return True, True
        return None

    monkeypatch.setattr(
        snapshots,
        "prepare_snapshot_root_async",
        _fake_prepare_snapshot_root_async,
    )
    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    prepared = await snapshots.prepare_project_snapshot_root_async(prepare_meta)
    await snapshots.delete_project_snapshot_root_async("/tmp/project-repo")
    await snapshots.delete_snapshot_async(prepare_meta)

    assert prepared.name == "repo"
    fn_names = [getattr(call[0], "__name__", "") for call in calls]
    assert "_clone_shared_snapshot_to_project" in fn_names
    assert "_clear_dir_and_rmdir" in fn_names




def test_download_snapshot_archive_from_s3_streams_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {"value": False}

    class _Body:
        def iter_chunks(self, chunk_size: int = 0):
            _ = chunk_size
            yield b"abc"
            yield b""
            yield b"def"

        def close(self) -> None:
            closed["value"] = True

    class _S3:
        def get_object(self, *, Bucket: str, Key: str):
            assert Bucket == "bucket"
            assert Key == "snapshots/sha/repo.zip"
            return {"Body": _Body()}

    monkeypatch.setattr(snapshots, "_s3_client", lambda: _S3())

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

    snapshots._download_snapshot_archive_from_s3(meta, out)

    assert out.read_bytes() == b"abcdef"
    assert closed["value"] is True




def test_download_snapshot_archive_from_s3_cleans_partial_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Body:
        def iter_chunks(self, chunk_size: int = 0):
            _ = chunk_size
            yield b"abc"
            raise RuntimeError("stream broken")

        def close(self) -> None:
            return None

    class _S3:
        def get_object(self, *, Bucket: str, Key: str):
            assert Bucket == "bucket"
            assert Key == "snapshots/sha/repo.zip"
            return {"Body": _Body()}

    monkeypatch.setattr(snapshots, "_s3_client", lambda: _S3())

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
        snapshots._download_snapshot_archive_from_s3(meta, out)

    assert not out.exists()


@pytest.mark.anyio
async def test_delete_snapshot_async_cleans_local_dir_and_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    meta = snapshots.SnapshotMeta(
        storage="s3",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
        bucket="bucket",
        key="snapshots/sha/repo.zip",
    )

    async def _fake_to_thread(func, *args, **kwargs):
        _ = args, kwargs
        name = getattr(func, "__name__", "")
        calls.append(name)
        if name == "_path_exists_and_is_dir":
            return True, True
        return None

    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    await snapshots.delete_snapshot_async(meta)

    assert "_clear_dir_and_rmdir" in calls
    assert "_delete_snapshot_from_s3" in calls






@pytest.mark.anyio
async def test_delete_snapshot_async_unlinks_archive_on_root_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    meta = snapshots.SnapshotMeta(
        storage="local",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
    )

    async def _fake_to_thread(func, *args, **kwargs):
        _ = args, kwargs
        name = getattr(func, "__name__", "")
        calls.append(name)
        if name == "_path_exists_and_is_dir":
            if len(calls) <= 2:
                return False, False
            return True, True
        if name == "_resolve_and_clear_dir_if_exists":
            raise RuntimeError("root cleanup failed")
        if name == "_clear_dir_and_rmdir":
            raise RuntimeError("root cleanup failed")
        return None

    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    with pytest.raises(RuntimeError, match="root cleanup failed"):
        await snapshots.delete_snapshot_async(meta)

    assert "unlink" in calls

@pytest.mark.anyio
async def test_delete_snapshot_async_awaits_s3_task_on_local_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    meta = snapshots.SnapshotMeta(
        storage="s3",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
        bucket="bucket",
        key="snapshots/sha/repo.zip",
    )

    async def _fake_to_thread(func, *args, **kwargs):
        _ = args, kwargs
        name = getattr(func, "__name__", "")
        calls.append(name)
        if name == "_path_exists_and_is_dir":
            return True, True
        if name == "_clear_dir_and_rmdir":
            raise RuntimeError("cleanup failed")
        return None

    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await snapshots.delete_snapshot_async(meta)

    assert "_delete_snapshot_from_s3" in calls

@pytest.mark.anyio
async def test_delete_snapshot_async_offloads_s3_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    meta = snapshots.SnapshotMeta(
        storage="s3",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
        bucket="bucket",
        key="snapshots/sha/repo.zip",
    )

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append(getattr(func, "__name__", ""))
        name = getattr(func, "__name__", "")
        if name == "_path_exists_and_is_dir":
            return False, False
        return None

    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    await snapshots.delete_snapshot_async(meta)

    assert "_delete_snapshot_from_s3" in calls
