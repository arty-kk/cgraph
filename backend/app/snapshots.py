# backend/app/snapshots.py
from __future__ import annotations

import asyncio
import hashlib
import inspect
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config import settings
from .errors import BadRequestError
from .infra.fs_runtime import run_fs_io_async
from .logging import get_logger
from .s3_runtime import get_s3_client
from .utils import sha256_file

logger = get_logger("stubgraph.snapshots")

_SNAPSHOT_S3_IO_SEMAPHORE: asyncio.Semaphore | None = None
_SNAPSHOT_S3_IO_SEMAPHORE_LOOP: asyncio.AbstractEventLoop | None = None
_SNAPSHOT_S3_IO_SEMAPHORE_LOCK: asyncio.Lock | None = None
_SNAPSHOT_S3_IO_SEMAPHORE_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


def _get_snapshot_s3_io_semaphore_lock() -> asyncio.Lock:
    global _SNAPSHOT_S3_IO_SEMAPHORE_LOCK, _SNAPSHOT_S3_IO_SEMAPHORE_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _SNAPSHOT_S3_IO_SEMAPHORE_LOCK is None or _SNAPSHOT_S3_IO_SEMAPHORE_LOCK_LOOP is not loop:
        _SNAPSHOT_S3_IO_SEMAPHORE_LOCK = asyncio.Lock()
        _SNAPSHOT_S3_IO_SEMAPHORE_LOCK_LOOP = loop
    return _SNAPSHOT_S3_IO_SEMAPHORE_LOCK


async def _get_snapshot_s3_io_semaphore() -> asyncio.Semaphore:
    global _SNAPSHOT_S3_IO_SEMAPHORE, _SNAPSHOT_S3_IO_SEMAPHORE_LOOP
    loop = asyncio.get_running_loop()
    async with _get_snapshot_s3_io_semaphore_lock():
        if _SNAPSHOT_S3_IO_SEMAPHORE is None or _SNAPSHOT_S3_IO_SEMAPHORE_LOOP is not loop:
            concurrency = max(1, int(settings.snapshot_s3_concurrency))
            _SNAPSHOT_S3_IO_SEMAPHORE = asyncio.Semaphore(concurrency)
            _SNAPSHOT_S3_IO_SEMAPHORE_LOOP = loop
    semaphore = _SNAPSHOT_S3_IO_SEMAPHORE
    if semaphore is None:
        raise SnapshotError("Failed to initialize snapshot S3 I/O semaphore")
    return semaphore


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotMeta:
    storage: str
    sha256: str
    archive_name: str
    archive_ext: str
    size: int
    file: str
    root_dir: str
    bucket: str | None = None
    key: str | None = None


def snapshot_meta_from_dict(data: dict) -> SnapshotMeta:
    return SnapshotMeta(
        storage=str(data.get("storage") or ""),
        sha256=str(data.get("sha256") or ""),
        archive_name=str(data.get("archive_name") or ""),
        archive_ext=str(data.get("archive_ext") or ""),
        size=int(data.get("size") or 0),
        file=str(data.get("file") or ""),
        root_dir=str(data.get("root_dir") or ""),
        bucket=data.get("bucket"),
        key=data.get("key"),
    )


def _snapshot_dir(sha: str) -> Path:
    return (settings.db_dir / "snapshots" / sha).resolve()


def _local_archive_path(sha: str, ext: str) -> Path:
    return _snapshot_dir(sha) / f"archive{ext}"


def _archive_ext(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".tar.gz"):
        return ".tar.gz"
    if lower.endswith(".tgz"):
        return ".tgz"
    if lower.endswith(".tar"):
        return ".tar"
    if lower.endswith(".zip"):
        return ".zip"
    raise BadRequestError("Неподдерживаемый формат архива (ожидаются .zip или .tar/.tar.gz/.tgz)")


def _s3_snapshot_key(sha: str, archive_name: str) -> str:
    prefix = (settings.s3_prefix or "").strip().strip("/")
    if prefix:
        return f"{prefix}/snapshots/{sha}/{archive_name}"
    return f"snapshots/{sha}/{archive_name}"


def _ensure_storage_backend() -> str:
    backend = (settings.storage_backend or "local").strip().lower()
    if backend not in {"local", "s3"}:
        raise SnapshotError(f"Unsupported storage backend: {backend}")
    return backend


def _assert_safe_path(base: Path, member_path: str) -> Path:
    target = (base / member_path).resolve()
    if base not in target.parents and target != base:
        raise BadRequestError("Архив содержит путь вне корневой директории")
    return target


def _validate_limits(file_count: int, total_bytes: int, file_bytes: int) -> None:
    if file_count > settings.snapshot_max_files:
        raise BadRequestError(
            "Слишком много файлов в архиве",
            context={"max_files": settings.snapshot_max_files, "files": file_count},
        )
    if total_bytes > settings.snapshot_max_unpacked_bytes:
        raise BadRequestError(
            "Слишком большой распакованный размер",
            context={
                "max_unpacked_bytes": settings.snapshot_max_unpacked_bytes,
                "bytes": total_bytes,
            },
        )
    if file_bytes > settings.snapshot_max_file_bytes:
        raise BadRequestError(
            "Файл в архиве превышает лимит",
            context={"max_file_bytes": settings.snapshot_max_file_bytes, "bytes": file_bytes},
        )


def _extract_zip(archive_path: Path, root_dir: Path) -> None:
    total = 0
    count = 0
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            count += 1
            total += int(info.file_size or 0)
            _validate_limits(count, total, int(info.file_size or 0))
            _assert_safe_path(root_dir, info.filename)

        for info in zf.infolist():
            if info.is_dir():
                continue
            _assert_safe_path(root_dir, info.filename)
            zf.extract(info, root_dir)


def _extract_tar(archive_path: Path, root_dir: Path) -> None:
    total = 0
    count = 0
    with tarfile.open(archive_path, "r:*") as tf:
        members = []
        for member in tf.getmembers():
            if not member.isfile():
                continue
            count += 1
            size = int(member.size or 0)
            total += size
            _validate_limits(count, total, size)
            _assert_safe_path(root_dir, member.name)
            members.append(member)

        tf.extractall(root_dir, members=members)


def _clear_dir_contents(root_dir: Path) -> None:
    for path in sorted(root_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()


def _clear_dir_and_rmdir(root_dir: Path) -> None:
    _clear_dir_contents(root_dir)
    root_dir.rmdir()


def _clone_shared_snapshot_to_project(shared_root: Path, project_root: Path) -> None:
    project_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(shared_root, project_root)


def _resolve_path_and_dir_state(path: Path) -> tuple[Path, bool, bool]:
    resolved = path.resolve()
    exists = resolved.exists()
    return resolved, exists, bool(exists and resolved.is_dir())


def _resolve_path(path: Path) -> Path:
    return path.resolve()


def _resolve_and_clear_dir_if_exists(path: Path) -> None:
    root_dir, exists, is_dir = _resolve_path_and_dir_state(path)
    if exists and is_dir:
        _clear_dir_contents(root_dir)


def _dir_has_entries(path: Path) -> bool:
    return any(path.iterdir())


def _snapshot_root_state(root_dir: Path, marker_path: Path) -> tuple[bool, bool]:
    has_any_files = any(root_dir.iterdir())
    marker_exists = bool(has_any_files and marker_path.exists())
    return has_any_files, marker_exists


def _ensure_root_and_get_state(root_dir: Path, marker_path: Path) -> tuple[bool, bool]:
    root_dir.mkdir(parents=True, exist_ok=True)
    return _snapshot_root_state(root_dir, marker_path)


def _resolve_root_and_get_state(
    path: Path,
    marker_name: str = ".extracted_ok",
) -> tuple[Path, Path, bool, bool]:
    root_dir = path.resolve()
    marker_path = root_dir / marker_name
    has_any_files, marker_exists = _ensure_root_and_get_state(root_dir, marker_path)
    return root_dir, marker_path, has_any_files, marker_exists


async def _download_snapshot_archive_from_s3(meta: SnapshotMeta, archive_path: Path) -> None:
    if not meta.bucket or not meta.key:
        raise SnapshotError("Missing S3 snapshot metadata")
    async with (await _get_snapshot_s3_io_semaphore()):
        resp = await get_s3_client().get_object(Bucket=meta.bucket, Key=meta.key)
    body = resp.get("Body")
    if body is None:
        raise SnapshotError("Empty snapshot payload")
    try:
        chunks: list[bytes] = []
        buffered = 0
        flush_threshold = 4 * 1024 * 1024
        while True:
            async with (await _get_snapshot_s3_io_semaphore()):
                chunk = await body.read(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            buffered += len(chunk)
            if buffered >= flush_threshold:
                await run_fs_io_async(
                    _append_file_chunks,
                    archive_path,
                    chunks,
                    operation="snapshots.archive.append_chunks",
                    lane="bulk",
                )
                chunks.clear()
                buffered = 0
        if chunks:
            await run_fs_io_async(
                _append_file_chunks,
                archive_path,
                chunks,
                operation="snapshots.archive.append_chunks",
                lane="bulk",
            )
    except Exception:
        await _cleanup_path_async(archive_path)
        raise
    finally:
        await _maybe_await_close(body)




async def _maybe_await_close(body) -> None:
    close_fn = getattr(body, "close", None)
    if close_fn is None:
        return
    close_result = close_fn()
    if inspect.isawaitable(close_result):
        await close_result


def _append_file_chunks(path: Path, chunks: list[bytes]) -> None:
    with path.open("ab") as tmp:
        for chunk in chunks:
            tmp.write(chunk)


def _read_chunk_batch(stream, chunk_size: int, batch_size: int = 4) -> list[bytes]:
    chunks: list[bytes] = []
    for _ in range(batch_size):
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
    return chunks


def _open_archive_read_stream(archive_path: Path):
    return archive_path.open("rb")


def _close_archive_read_stream(stream) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except ValueError:
        return


async def _cleanup_path_async(path: Path) -> None:
    await run_fs_io_async(
        path.unlink,
        missing_ok=True,
        operation="snapshots.path.unlink",
        lane="bulk",
    )


async def _upload_archive_to_s3(archive_path: Path, bucket: str, key: str) -> None:
    client = get_s3_client()
    upload_id = None
    parts: list[dict[str, str | int]] = []
    chunk_size = 8 * 1024 * 1024
    concurrency = max(1, int(settings.snapshot_s3_concurrency))
    queue: asyncio.Queue[tuple[int, bytes] | None] = asyncio.Queue(maxsize=concurrency)
    pipeline_error: BaseException | None = None

    def _set_pipeline_error(exc: BaseException) -> None:
        nonlocal pipeline_error
        if pipeline_error is None:
            pipeline_error = exc

    async def _upload_worker() -> None:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                part_number, chunk = item
                if pipeline_error is not None:
                    continue
                async with (await _get_snapshot_s3_io_semaphore()):
                    resp = await client.upload_part(
                        Bucket=bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=chunk,
                    )
                etag = resp.get("ETag")
                if not isinstance(etag, str) or not etag:
                    raise SnapshotError("S3 upload part missing ETag")
                parts.append({"ETag": etag, "PartNumber": part_number})
            except BaseException as exc:  # noqa: BLE001
                _set_pipeline_error(exc)
            finally:
                queue.task_done()

    def _validated_sorted_parts(
        upload_parts: list[dict[str, str | int]],
    ) -> list[dict[str, str | int]]:
        if not upload_parts:
            raise SnapshotError("Multipart upload produced no parts")
        sorted_parts = sorted(upload_parts, key=lambda item: int(item["PartNumber"]))
        for expected_part, part in enumerate(sorted_parts, start=1):
            part_number = int(part.get("PartNumber") or 0)
            etag = part.get("ETag")
            if part_number != expected_part:
                raise SnapshotError("Multipart upload parts are incomplete or out of sequence")
            if not isinstance(etag, str) or not etag:
                raise SnapshotError("Multipart upload part has invalid ETag")
        return sorted_parts

    try:
        async with (await _get_snapshot_s3_io_semaphore()):
            create_resp = await client.create_multipart_upload(Bucket=bucket, Key=key)
            upload_id = create_resp.get("UploadId")
            if not upload_id:
                raise SnapshotError("Failed to start multipart upload")

        async def _shutdown_workers(workers: list[asyncio.Task[None]]) -> None:
            for _ in workers:
                await queue.put(None)
            await queue.join()
            await asyncio.gather(*workers, return_exceptions=True)

        stream = await run_fs_io_async(
            _open_archive_read_stream,
            archive_path,
            operation="snapshots.archive.open_read_stream",
            lane="bulk",
        )
        workers = [asyncio.create_task(_upload_worker()) for _ in range(concurrency)]
        producer_part_number = 1
        try:
            while True:
                if pipeline_error is not None:
                    raise pipeline_error

                chunk_batch = await run_fs_io_async(
                    _read_chunk_batch,
                    stream,
                    chunk_size,
                    operation="snapshots.archive.read_chunks",
                    lane="bulk",
                )
                if not chunk_batch:
                    break

                for chunk in chunk_batch:
                    if pipeline_error is not None:
                        raise pipeline_error
                    await queue.put((producer_part_number, chunk))
                    producer_part_number += 1
        finally:
            await run_fs_io_async(
                _close_archive_read_stream,
                stream,
                operation="snapshots.archive.close_read_stream",
                lane="bulk",
            )
            shutdown_task = asyncio.create_task(_shutdown_workers(workers))
            try:
                await asyncio.shield(shutdown_task)
            except asyncio.CancelledError:
                await shutdown_task
                raise

        if pipeline_error is not None:
            raise pipeline_error

        validated_parts = _validated_sorted_parts(parts)

        async with (await _get_snapshot_s3_io_semaphore()):
            await client.complete_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": validated_parts},
            )
    except BaseException:
        if upload_id:
            try:
                async with (await _get_snapshot_s3_io_semaphore()):
                    await client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to abort multipart upload", extra={"reason": str(exc)})
        raise


async def _delete_snapshot_from_s3(bucket: str, key: str) -> None:
    await get_s3_client().delete_object(Bucket=bucket, Key=key)


def _archive_needs_update(archive_path: Path, expected_size: int, expected_sha: str) -> bool:
    if archive_path.stat().st_size != expected_size:
        return True
    return sha256_file(archive_path) != expected_sha


async def _ensure_local_snapshot_archive(meta: SnapshotMeta) -> Path:
    archive_path = _local_archive_path(meta.sha256, meta.archive_ext)
    exists = await run_fs_io_async(
        archive_path.exists,
        operation="snapshots.archive.exists",
        lane="bulk",
    )
    if not exists and meta.storage == "s3":
        await _download_snapshot_archive_from_s3(meta, archive_path)
    return archive_path


def _extract_archive_to_root(
    archive_ext: str,
    archive_path: Path,
    root_dir: Path,
    marker_path: Path,
) -> None:
    if archive_ext == ".zip":
        _extract_zip(archive_path, root_dir)
    else:
        _extract_tar(archive_path, root_dir)
    marker_path.write_text("ok")


async def _ensure_archive_and_extract(
    meta: SnapshotMeta,
    root_dir: Path,
    marker_path: Path,
) -> None:
    archive_path = await _ensure_local_snapshot_archive(meta)
    await run_fs_io_async(
        _extract_archive_to_root,
        meta.archive_ext,
        archive_path,
        root_dir,
        marker_path,
        operation="snapshots.extract.archive",
        lane="bulk",
    )


def _finalize_local_archive(
    tmp_path: Path,
    archive_path: Path,
    expected_size: int,
    expected_sha: str,
) -> None:
    if archive_path.exists():
        if _archive_needs_update(archive_path, expected_size, expected_sha):
            archive_path.unlink(missing_ok=True)
            tmp_path.replace(archive_path)
        else:
            tmp_path.unlink(missing_ok=True)
        return
    tmp_path.replace(archive_path)


def _is_project_snapshot_root(root_dir: Path) -> bool:
    base_dir = (settings.db_dir / "snapshots").resolve()
    if base_dir not in root_dir.parents:
        return False
    try:
        rel_parts = root_dir.relative_to(base_dir).parts
    except ValueError:
        return False
    return len(rel_parts) >= 4 and rel_parts[1] == "projects"


def _path_exists_and_is_dir(path: Path) -> tuple[bool, bool]:
    exists = path.exists()
    return exists, bool(exists and path.is_dir())


async def _path_exists_and_is_dir_async(path: Path) -> tuple[bool, bool]:
    return await run_fs_io_async(
        _path_exists_and_is_dir,
        path,
        operation="snapshots.path.exists_dir",
        lane="bulk",
    )


async def _unlink_if_exists_async(path: Path) -> None:
    await _cleanup_path_async(path)


async def prepare_snapshot_root_async(meta: SnapshotMeta) -> Path:
    root_dir, marker_path, has_any_files, marker_exists = await run_fs_io_async(
        _resolve_root_and_get_state,
        settings.db_dir / meta.root_dir,
        operation="snapshots.root.resolve_state",
        lane="bulk",
    )
    if has_any_files:
        if marker_exists:
            return root_dir
        await run_fs_io_async(
            _clear_dir_contents,
            root_dir,
            operation="snapshots.dir.clear",
            lane="bulk",
        )

    await _ensure_archive_and_extract(
        meta,
        root_dir,
        marker_path,
    )
    return root_dir


async def prepare_project_snapshot_root_async(meta: SnapshotMeta) -> Path:
    shared_root = await prepare_snapshot_root_async(meta)
    project_base = _snapshot_dir(meta.sha256) / "projects" / uuid4().hex
    project_root = project_base / "repo"
    await run_fs_io_async(
        _clone_shared_snapshot_to_project,
        shared_root,
        project_root,
        operation="snapshots.project.clone",
        lane="bulk",
    )
    return project_root


async def delete_project_snapshot_root_async(root_path: str | Path) -> None:
    root_dir, exists, is_dir = await run_fs_io_async(
        _resolve_path_and_dir_state,
        Path(root_path),
        operation="snapshots.path.resolve_state",
        lane="bulk",
    )
    if not _is_project_snapshot_root(root_dir):
        return
    if exists and is_dir:
        await run_fs_io_async(
            _clear_dir_and_rmdir,
            root_dir,
            operation="snapshots.dir.clear_rmdir",
            lane="bulk",
        )


async def delete_snapshot_async(meta: SnapshotMeta) -> None:
    s3_delete_task: asyncio.Task[None] | None = None

    async def _delete_s3_if_needed() -> None:
        if meta.storage != "s3" or not meta.bucket or not meta.key:
            return
        try:
            await _delete_snapshot_from_s3(meta.bucket, meta.key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete snapshot from S3", extra={"reason": str(exc)})

    if meta.storage == "s3" and meta.bucket and meta.key:
        s3_delete_task = asyncio.create_task(_delete_s3_if_needed())

    try:
        snapshot_dir = _snapshot_dir(meta.sha256)
        snapshot_exists, snapshot_is_dir = await _path_exists_and_is_dir_async(snapshot_dir)

        if snapshot_exists and snapshot_is_dir:
            await run_fs_io_async(
                _clear_dir_and_rmdir,
                snapshot_dir,
                operation="snapshots.dir.clear_rmdir",
                lane="bulk",
            )
        else:
            archive_path = _local_archive_path(meta.sha256, meta.archive_ext)
            unlink_archive_task = asyncio.create_task(_unlink_if_exists_async(archive_path))
            try:
                await run_fs_io_async(
                    _resolve_and_clear_dir_if_exists,
                    settings.db_dir / meta.root_dir,
                    operation="snapshots.dir.resolve_clear_if_exists",
                    lane="bulk",
                )
            finally:
                await unlink_archive_task
    finally:
        if s3_delete_task is not None:
            await s3_delete_task


async def store_snapshot_upload(upload_file, archive_name: str) -> SnapshotMeta:
    await upload_file.seek(0)
    tmp_dir = settings.db_dir / "snapshots" / "tmp"
    await run_fs_io_async(
        tmp_dir.mkdir,
        parents=True,
        exist_ok=True,
        operation="snapshots.tmp.mkdir",
        lane="bulk",
    )

    ext = _archive_ext(archive_name)
    tmp_path = tmp_dir / f"{uuid4().hex}{ext}"

    total = 0
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    buffered = 0
    flush_threshold = 4 * 1024 * 1024
    try:
        while True:
            chunk = await upload_file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.snapshot_max_bytes:
                raise BadRequestError(
                    "Архив слишком большой",
                    context={"max_bytes": settings.snapshot_max_bytes, "size": total},
                )
            hasher.update(chunk)
            chunks.append(chunk)
            buffered += len(chunk)
            if buffered >= flush_threshold:
                await run_fs_io_async(
                    _append_file_chunks,
                    tmp_path,
                    chunks,
                    operation="snapshots.archive.append_chunks",
                    lane="bulk",
                )
                chunks.clear()
                buffered = 0

        if chunks:
            await run_fs_io_async(
                _append_file_chunks,
                tmp_path,
                chunks,
                operation="snapshots.archive.append_chunks",
                lane="bulk",
            )
    except Exception:
        await _cleanup_path_async(tmp_path)
        raise

    if total <= 0:
        await _cleanup_path_async(tmp_path)
        raise BadRequestError("Архив пустой")

    sha = hasher.hexdigest()
    root_dir = _snapshot_dir(sha)
    await run_fs_io_async(
        root_dir.mkdir,
        parents=True,
        exist_ok=True,
        operation="snapshots.root.mkdir",
        lane="bulk",
    )
    archive_path = _local_archive_path(sha, ext)

    await run_fs_io_async(
        _finalize_local_archive,
        tmp_path,
        archive_path,
        total,
        sha,
        operation="snapshots.archive.finalize",
        lane="bulk",
    )

    backend = _ensure_storage_backend()
    bucket = None
    key = None
    if backend == "s3":
        bucket = settings.s3_bucket
        if not bucket:
            raise SnapshotError("S3 bucket is not configured")
        key = _s3_snapshot_key(sha, archive_name)
        try:
            await _upload_archive_to_s3(archive_path, bucket, key)
        except Exception as exc:  # noqa: BLE001
            raise SnapshotError(f"Failed to upload snapshot to S3: {exc}") from exc

    return SnapshotMeta(
        storage=backend,
        sha256=sha,
        archive_name=archive_name,
        archive_ext=ext,
        size=total,
        file=str(archive_path.relative_to(settings.db_dir)),
        root_dir=str((root_dir / "repo").relative_to(settings.db_dir)),
        bucket=bucket,
        key=key,
    )
