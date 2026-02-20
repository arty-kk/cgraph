# backend/app/storage.py
"""Storage abstraction for large artifacts (e.g., patch blobs).

Публичный API этого модуля — только async-функции:
- store_patch_blob_async
- read_patch_blob_async
- delete_patch_blob_async
- delete_patch_blob_by_sha_async
- get_patch_download_url_async
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings
from .infra.fs_runtime import run_fs_io_async
from .logging import get_logger
from .s3_runtime import get_s3_client
from .utils import sha256_text

logger = get_logger("stubgraph.storage")

_S3_SIGNED_URL_SEMAPHORE = asyncio.Semaphore(settings.s3_signed_url_concurrency_limit)


class StorageError(RuntimeError):
    pass


def _storage_backend() -> str:
    backend = (settings.storage_backend or "local").strip().lower()
    if backend not in {"local", "s3"}:
        raise StorageError(f"Unsupported storage backend: {backend}")
    return backend


def _expires_at() -> str | None:
    days = int(settings.patch_retention_days or 0)
    if days <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expiry


def _local_patch_path(sha: str) -> Path:
    base = Path(settings.db_dir).resolve()
    return (base / "patches" / f"{sha}.diff").resolve()


def _s3_patch_key(sha: str) -> str:
    prefix = (settings.s3_prefix or "").strip().strip("/")
    base = f"{prefix}/patches/{sha}.diff" if prefix else f"patches/{sha}.diff"
    return base


def _s3_signed_url(bucket: str, key: str) -> str | None:
    try:
        client = get_s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=int(settings.s3_signed_url_ttl_seconds or 3600),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to generate signed URL", extra={"reason": str(exc)})
        return None


async def _s3_signed_url_async(bucket: str, key: str) -> str | None:
    async with _S3_SIGNED_URL_SEMAPHORE:
        try:
            return await asyncio.to_thread(_s3_signed_url, bucket, key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to generate signed URL", extra={"reason": str(exc)})
            return None


def _write_patch_blob_if_missing(path: Path, patch_text: str) -> None:
    with path.open("x", encoding="utf-8") as f:
        f.write(patch_text)


async def _maybe_await_close(body) -> None:
    close_fn = getattr(body, "close", None)
    if close_fn is None:
        return
    close_result = close_fn()
    if asyncio.iscoroutine(close_result):
        await close_result


async def store_patch_blob_async(patch_text: str) -> dict:
    sha = sha256_text(patch_text)
    expires_at = _expires_at()
    backend = _storage_backend()

    if backend == "local":
        fp = _local_patch_path(sha)
        base = Path(settings.db_dir).resolve()
        if base not in fp.parents and fp != base:
            raise StorageError("Refusing to write patch blob outside db_dir")
        await run_fs_io_async(
            fp.parent.mkdir,
            parents=True,
            exist_ok=True,
            operation="storage.local.mkdir",
        )
        try:
            await run_fs_io_async(
                _write_patch_blob_if_missing,
                fp,
                patch_text,
                operation="storage.local.write_if_missing",
            )
        except FileExistsError:
            pass
        return {
            "storage": "local",
            "sha256": sha,
            "file": f"patches/{sha}.diff",
            "expires_at": expires_at,
        }

    bucket = settings.s3_bucket
    if not bucket:
        raise StorageError("S3 bucket is not configured")
    key = _s3_patch_key(sha)
    client = get_s3_client()
    await client.put_object(
        Bucket=bucket,
        Key=key,
        Body=patch_text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    meta = {
        "storage": "s3",
        "sha256": sha,
        "bucket": bucket,
        "key": key,
        "expires_at": expires_at,
    }
    url = await _s3_signed_url_async(bucket, key)
    if url:
        meta["download_url"] = url
    return meta


async def read_patch_blob_async(meta: dict) -> str:
    expires_at = meta.get("expires_at") if isinstance(meta, dict) else None
    if _is_expired(expires_at if isinstance(expires_at, str) else None):
        await delete_patch_blob_async(meta)
        raise StorageError("Patch blob expired")

    storage = (meta.get("storage") or "").strip().lower() if isinstance(meta, dict) else ""
    if storage == "s3":
        bucket = meta.get("bucket")
        key = meta.get("key")
        if not isinstance(bucket, str) or not isinstance(key, str):
            raise StorageError("Missing S3 patch metadata")
        client = get_s3_client()
        resp = await client.get_object(Bucket=bucket, Key=key)
        body = resp.get("Body")
        if body is None:
            raise StorageError("Empty S3 response body")
        try:
            data = await body.read()
        finally:
            await _maybe_await_close(body)
        return data.decode("utf-8", errors="replace")

    sha = meta.get("sha256")
    if not isinstance(sha, str) or not sha:
        raise StorageError("Missing patch sha")
    fp = _local_patch_path(sha)
    base = Path(settings.db_dir).resolve()
    if base not in fp.parents and fp != base:
        raise StorageError("Invalid patch path")
    exists = await run_fs_io_async(fp.exists, operation="storage.local.exists")
    is_file = await run_fs_io_async(fp.is_file, operation="storage.local.is_file")
    if not exists or not is_file:
        raise StorageError("Patch blob not found")
    return await run_fs_io_async(
        fp.read_text,
        encoding="utf-8",
        errors="replace",
        operation="storage.local.read_text",
    )


async def delete_patch_blob_async(meta: dict | None) -> None:
    if not isinstance(meta, dict):
        return
    storage = (meta.get("storage") or "").strip().lower()
    if storage == "s3":
        bucket = meta.get("bucket")
        key = meta.get("key")
        if isinstance(bucket, str) and isinstance(key, str):
            try:
                await get_s3_client().delete_object(Bucket=bucket, Key=key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to delete S3 patch blob", extra={"reason": str(exc)})
        return

    sha = meta.get("sha256")
    if isinstance(sha, str) and sha:
        await delete_patch_blob_by_sha_async(sha)


async def delete_patch_blob_by_sha_async(sha: str) -> None:
    if not isinstance(sha, str) or not sha:
        return

    fp = _local_patch_path(sha)
    base = Path(settings.db_dir).resolve()
    if base not in fp.parents and fp != base:
        logger.warning("Refusing to delete patch blob outside db_dir", extra={"sha": sha})
        return
    try:
        await run_fs_io_async(fp.unlink, True, operation="storage.local.unlink")
    except Exception as error:  # noqa: BLE001
        logger.warning("Failed to delete patch blob", extra={"sha": sha, "reason": str(error)})

    backend = _storage_backend()
    if backend != "s3":
        return
    bucket = settings.s3_bucket
    if not bucket:
        return
    key = _s3_patch_key(sha)
    try:
        await get_s3_client().delete_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete S3 patch blob", extra={"reason": str(exc)})


async def get_patch_download_url_async(meta: dict) -> str | None:
    if not isinstance(meta, dict):
        return None
    storage = (meta.get("storage") or "").strip().lower()
    if storage != "s3":
        return None
    bucket = meta.get("bucket")
    key = meta.get("key")
    if not isinstance(bucket, str) or not isinstance(key, str):
        return None
    return await _s3_signed_url_async(bucket, key)
