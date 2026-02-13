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
from .utils import sha256_bytes, sha256_file

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


def store_snapshot_blob(data: bytes, archive_name: str) -> SnapshotMeta:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise BadRequestError("Архив пустой")
    if not isinstance(archive_name, str) or not archive_name.strip():
        raise BadRequestError("Имя архива обязательно")

    if len(data) > settings.snapshot_max_bytes:
        raise BadRequestError(
            "Архив слишком большой",
            context={"max_bytes": settings.snapshot_max_bytes, "size": len(data)},
        )

    ext = _archive_ext(archive_name)
    sha = sha256_bytes(data)
    root_dir = _snapshot_dir(sha)
    root_dir.mkdir(parents=True, exist_ok=True)
    archive_path = _local_archive_path(sha, ext)
    if archive_path.exists():
        needs_update = archive_path.stat().st_size != len(data)
        if not needs_update:
            existing_sha = sha256_bytes(archive_path.read_bytes())
            needs_update = existing_sha != sha
        if needs_update:
            archive_path.write_bytes(data)
    else:
        archive_path.write_bytes(data)

    backend = _ensure_storage_backend()
    bucket = None
    key = None
    if backend == "s3":
        bucket = settings.s3_bucket
        if not bucket:
            raise SnapshotError("S3 bucket is not configured")
        key = _s3_snapshot_key(sha, archive_name)
        try:
            _s3_client().put_object(Bucket=bucket, Key=key, Body=data)
        except Exception as exc:  # noqa: BLE001
            raise SnapshotError(f"Failed to upload snapshot to S3: {exc}") from exc

    return SnapshotMeta(
        storage=backend,
        sha256=sha,
        archive_name=archive_name,
        archive_ext=ext,
        size=len(data),
        file=str(archive_path.relative_to(settings.db_dir)),
        root_dir=str((root_dir / "repo").relative_to(settings.db_dir)),
        bucket=bucket,
        key=key,
    )


def store_snapshot_stream(fileobj, archive_name: str) -> SnapshotMeta:
    if not isinstance(archive_name, str) or not archive_name.strip():
        raise BadRequestError("Имя архива обязательно")

    ext = _archive_ext(archive_name)
    tmp_dir = settings.db_dir / "snapshots" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid4().hex}{ext}"

    total = 0
    hasher = hashlib.sha256()
    try:
        with tmp_path.open("wb") as tmp:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.snapshot_max_bytes:
                    raise BadRequestError(
                        "Архив слишком большой",
                        context={"max_bytes": settings.snapshot_max_bytes, "size": total},
                    )
                hasher.update(chunk)
                tmp.write(chunk)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    if total <= 0:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise BadRequestError("Архив пустой")

    sha = hasher.hexdigest()
    root_dir = _snapshot_dir(sha)
    root_dir.mkdir(parents=True, exist_ok=True)
    archive_path = _local_archive_path(sha, ext)

    if archive_path.exists():
        needs_update = archive_path.stat().st_size != total
        if not needs_update:
            needs_update = sha256_file(archive_path) != sha
        if needs_update:
            archive_path.unlink(missing_ok=True)
            tmp_path.replace(archive_path)
        else:
            tmp_path.unlink(missing_ok=True)
    else:
        tmp_path.replace(archive_path)

    backend = _ensure_storage_backend()
    bucket = None
    key = None
    if backend == "s3":
        bucket = settings.s3_bucket
        if not bucket:
            raise SnapshotError("S3 bucket is not configured")
        key = _s3_snapshot_key(sha, archive_name)
        try:
            with archive_path.open("rb") as f:
                _s3_client().put_object(Bucket=bucket, Key=key, Body=f)
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


def prepare_snapshot_root(meta: SnapshotMeta) -> Path:
    root_dir = (settings.db_dir / meta.root_dir).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    marker_path = root_dir / ".extracted_ok"
    if any(root_dir.iterdir()):
        if marker_path.exists():
            return root_dir
        for path in sorted(root_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()

    archive_path = _local_archive_path(meta.sha256, meta.archive_ext)
    if not archive_path.exists() and meta.storage == "s3":
        if not meta.bucket or not meta.key:
            raise SnapshotError("Missing S3 snapshot metadata")
        resp = _s3_client().get_object(Bucket=meta.bucket, Key=meta.key)
        body = resp.get("Body")
        if body is None:
            raise SnapshotError("Empty snapshot payload")
        archive_path.write_bytes(body.read())

    if meta.archive_ext == ".zip":
        _extract_zip(archive_path, root_dir)
    else:
        _extract_tar(archive_path, root_dir)

    marker_path.write_text("ok")
    return root_dir


def prepare_project_snapshot_root(meta: SnapshotMeta) -> Path:
    shared_root = prepare_snapshot_root(meta)
    project_base = _snapshot_dir(meta.sha256) / "projects" / uuid4().hex
    project_root = project_base / "repo"
    project_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(shared_root, project_root)
    return project_root


def _is_project_snapshot_root(root_dir: Path) -> bool:
    base_dir = (settings.db_dir / "snapshots").resolve()
    if base_dir not in root_dir.parents:
        return False
    try:
        rel_parts = root_dir.relative_to(base_dir).parts
    except ValueError:
        return False
    return len(rel_parts) >= 4 and rel_parts[1] == "projects"


def delete_project_snapshot_root(root_path: str | Path) -> None:
    root_dir = Path(root_path).resolve()
    if not _is_project_snapshot_root(root_dir):
        return
    if root_dir.exists() and root_dir.is_dir():
        for path in sorted(root_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        root_dir.rmdir()


def delete_snapshot(meta: SnapshotMeta) -> None:
    archive_path = _local_archive_path(meta.sha256, meta.archive_ext)
    root_dir = (settings.db_dir / meta.root_dir).resolve()
    if root_dir.exists() and root_dir.is_dir():
        for path in sorted(root_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
    if archive_path.exists():
        archive_path.unlink(missing_ok=True)

    snapshot_dir = _snapshot_dir(meta.sha256)
    if snapshot_dir.exists() and snapshot_dir.is_dir():
        for path in sorted(snapshot_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        snapshot_dir.rmdir()

    if meta.storage == "s3" and meta.bucket and meta.key:
        try:
            _s3_client().delete_object(Bucket=meta.bucket, Key=meta.key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete snapshot from S3", extra={"reason": str(exc)})


async def store_snapshot_upload(upload_file, archive_name: str) -> SnapshotMeta:
    await upload_file.seek(0)
    return await asyncio.to_thread(store_snapshot_stream, upload_file.file, archive_name)
