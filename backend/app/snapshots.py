# backend/app/snapshots.py
from __future__ import annotations

import asyncio
import hashlib
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config import settings
from .errors import BadRequestError
from .logging import get_logger
from .utils import sha256_file

logger = get_logger("stubgraph.snapshots")


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


def _s3_client():
    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise SnapshotError("boto3 is required for S3 storage") from exc

    session = boto3.session.Session(
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
    )
    return session.client(
        "s3",
        region_name=settings.s3_region or None,
        endpoint_url=settings.s3_endpoint_url or None,
    )


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


def _resolve_root_and_get_state(path: Path, marker_name: str = ".extracted_ok") -> tuple[Path, Path, bool, bool]:
    root_dir = path.resolve()
    marker_path = root_dir / marker_name
    has_any_files, marker_exists = _ensure_root_and_get_state(root_dir, marker_path)
    return root_dir, marker_path, has_any_files, marker_exists


def _download_snapshot_archive_from_s3(meta: SnapshotMeta, archive_path: Path) -> None:
    if not meta.bucket or not meta.key:
        raise SnapshotError("Missing S3 snapshot metadata")
    resp = _s3_client().get_object(Bucket=meta.bucket, Key=meta.key)
    body = resp.get("Body")
    if body is None:
        raise SnapshotError("Empty snapshot payload")
    try:
        with archive_path.open("wb") as out:
            chunk_iter = getattr(body, "iter_chunks", None)
            if callable(chunk_iter):
                for chunk in chunk_iter(chunk_size=1024 * 1024):
                    if chunk:
                        out.write(chunk)
            else:
                out.write(body.read())
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        close_fn = getattr(body, "close", None)
        if callable(close_fn):
            close_fn()


def _append_file_chunk(path: Path, chunk: bytes) -> None:
    with path.open("ab") as tmp:
        tmp.write(chunk)


def _upload_archive_to_s3(archive_path: Path, bucket: str, key: str) -> None:
    with archive_path.open("rb") as f:
        _s3_client().put_object(Bucket=bucket, Key=key, Body=f)


def _delete_snapshot_from_s3(bucket: str, key: str) -> None:
    _s3_client().delete_object(Bucket=bucket, Key=key)


def _archive_needs_update(archive_path: Path, expected_size: int, expected_sha: str) -> bool:
    if archive_path.stat().st_size != expected_size:
        return True
    return sha256_file(archive_path) != expected_sha


def _ensure_local_snapshot_archive(meta: SnapshotMeta) -> Path:
    archive_path = _local_archive_path(meta.sha256, meta.archive_ext)
    if not archive_path.exists() and meta.storage == "s3":
        _download_snapshot_archive_from_s3(meta, archive_path)
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


def _ensure_archive_and_extract(
    meta: SnapshotMeta,
    root_dir: Path,
    marker_path: Path,
) -> None:
    archive_path = _ensure_local_snapshot_archive(meta)
    _extract_archive_to_root(meta.archive_ext, archive_path, root_dir, marker_path)


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
    return await asyncio.to_thread(_path_exists_and_is_dir, path)


async def _unlink_if_exists_async(path: Path) -> None:
    await asyncio.to_thread(path.unlink, True)


async def prepare_snapshot_root_async(meta: SnapshotMeta) -> Path:
    root_dir, marker_path, has_any_files, marker_exists = await asyncio.to_thread(
        _resolve_root_and_get_state,
        settings.db_dir / meta.root_dir,
    )
    if has_any_files:
        if marker_exists:
            return root_dir
        await asyncio.to_thread(_clear_dir_contents, root_dir)

    await asyncio.to_thread(
        _ensure_archive_and_extract,
        meta,
        root_dir,
        marker_path,
    )
    return root_dir


async def prepare_project_snapshot_root_async(meta: SnapshotMeta) -> Path:
    shared_root = await prepare_snapshot_root_async(meta)
    project_base = _snapshot_dir(meta.sha256) / "projects" / uuid4().hex
    project_root = project_base / "repo"
    await asyncio.to_thread(_clone_shared_snapshot_to_project, shared_root, project_root)
    return project_root


async def delete_project_snapshot_root_async(root_path: str | Path) -> None:
    root_dir, exists, is_dir = await asyncio.to_thread(
        _resolve_path_and_dir_state,
        Path(root_path),
    )
    if not _is_project_snapshot_root(root_dir):
        return
    if exists and is_dir:
        await asyncio.to_thread(_clear_dir_and_rmdir, root_dir)


async def delete_snapshot_async(meta: SnapshotMeta) -> None:
    s3_delete_task: asyncio.Task[None] | None = None

    async def _delete_s3_if_needed() -> None:
        if meta.storage != "s3" or not meta.bucket or not meta.key:
            return
        try:
            await asyncio.to_thread(_delete_snapshot_from_s3, meta.bucket, meta.key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete snapshot from S3", extra={"reason": str(exc)})

    if meta.storage == "s3" and meta.bucket and meta.key:
        s3_delete_task = asyncio.create_task(_delete_s3_if_needed())

    try:
        snapshot_dir = _snapshot_dir(meta.sha256)
        snapshot_exists, snapshot_is_dir = await _path_exists_and_is_dir_async(snapshot_dir)

        if snapshot_exists and snapshot_is_dir:
            await asyncio.to_thread(_clear_dir_and_rmdir, snapshot_dir)
        else:
            archive_path = _local_archive_path(meta.sha256, meta.archive_ext)
            unlink_archive_task = asyncio.create_task(_unlink_if_exists_async(archive_path))
            try:
                await asyncio.to_thread(
                    _resolve_and_clear_dir_if_exists,
                    settings.db_dir / meta.root_dir,
                )
            finally:
                await unlink_archive_task
    finally:
        if s3_delete_task is not None:
            await s3_delete_task


async def store_snapshot_upload(upload_file, archive_name: str) -> SnapshotMeta:
    await upload_file.seek(0)
    tmp_dir = settings.db_dir / "snapshots" / "tmp"
    await asyncio.to_thread(tmp_dir.mkdir, parents=True, exist_ok=True)

    ext = _archive_ext(archive_name)
    tmp_path = tmp_dir / f"{uuid4().hex}{ext}"

    total = 0
    hasher = hashlib.sha256()
    write_buffer = bytearray()
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
            write_buffer.extend(chunk)
            if len(write_buffer) >= flush_threshold:
                await asyncio.to_thread(_append_file_chunk, tmp_path, bytes(write_buffer))
                write_buffer.clear()

        if write_buffer:
            await asyncio.to_thread(_append_file_chunk, tmp_path, bytes(write_buffer))
    except Exception:
        await asyncio.to_thread(tmp_path.unlink, True)
        raise

    if total <= 0:
        await asyncio.to_thread(tmp_path.unlink, True)
        raise BadRequestError("Архив пустой")

    sha = hasher.hexdigest()
    root_dir = _snapshot_dir(sha)
    await asyncio.to_thread(root_dir.mkdir, parents=True, exist_ok=True)
    archive_path = _local_archive_path(sha, ext)

    await asyncio.to_thread(_finalize_local_archive, tmp_path, archive_path, total, sha)

    backend = _ensure_storage_backend()
    bucket = None
    key = None
    if backend == "s3":
        bucket = settings.s3_bucket
        if not bucket:
            raise SnapshotError("S3 bucket is not configured")
        key = _s3_snapshot_key(sha, archive_name)
        try:
            await asyncio.to_thread(_upload_archive_to_s3, archive_path, bucket, key)
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
