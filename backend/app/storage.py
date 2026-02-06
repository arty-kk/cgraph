# backend/app/storage.py
"""Storage abstraction for large artifacts (e.g., patch blobs).

Usage: call store_patch_blob() for large payloads, then read_patch_blob()
or get_patch_download_url() when returning the artifact to clients.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings
from .logging import get_logger
from .utils import sha256_text

logger = get_logger("stubgraph.storage")


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


def _s3_client():
    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise StorageError("boto3 is required for S3 storage") from exc

    session = boto3.session.Session(
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
    )
    return session.client(
        "s3",
        region_name=settings.s3_region or None,
        endpoint_url=settings.s3_endpoint_url or None,
    )


def _s3_patch_key(sha: str) -> str:
    prefix = (settings.s3_prefix or "").strip().strip("/")
    base = f"{prefix}/patches/{sha}.diff" if prefix else f"patches/{sha}.diff"
    return base


def _s3_signed_url(bucket: str, key: str) -> str | None:
    try:
        client = _s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=int(settings.s3_signed_url_ttl_seconds or 3600),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to generate signed URL", extra={"reason": str(exc)})
        return None


def store_patch_blob(patch_text: str) -> dict:
    sha = sha256_text(patch_text)
    expires_at = _expires_at()
    backend = _storage_backend()

    if backend == "local":
        fp = _local_patch_path(sha)
        base = Path(settings.db_dir).resolve()
        if base not in fp.parents and fp != base:
            raise StorageError("Refusing to write patch blob outside db_dir")
        fp.parent.mkdir(parents=True, exist_ok=True)
        try:
            with fp.open("x", encoding="utf-8") as f:
                f.write(patch_text)
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
    client = _s3_client()
    client.put_object(
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
    url = _s3_signed_url(bucket, key)
    if url:
        meta["download_url"] = url
    return meta


def read_patch_blob(meta: dict) -> str:
    expires_at = meta.get("expires_at") if isinstance(meta, dict) else None
    if _is_expired(expires_at if isinstance(expires_at, str) else None):
        delete_patch_blob(meta)
        raise StorageError("Patch blob expired")

    storage = (meta.get("storage") or "").strip().lower() if isinstance(meta, dict) else ""
    if storage == "s3":
        bucket = meta.get("bucket")
        key = meta.get("key")
        if not isinstance(bucket, str) or not isinstance(key, str):
            raise StorageError("Missing S3 patch metadata")
        client = _s3_client()
        resp = client.get_object(Bucket=bucket, Key=key)
        body = resp.get("Body")
        if body is None:
            raise StorageError("Empty S3 response body")
        data = body.read()
        return data.decode("utf-8", errors="replace")

    sha = meta.get("sha256")
    if not isinstance(sha, str) or not sha:
        raise StorageError("Missing patch sha")
    fp = _local_patch_path(sha)
    base = Path(settings.db_dir).resolve()
    if base not in fp.parents and fp != base:
        raise StorageError("Invalid patch path")
    if not fp.exists() or not fp.is_file():
        raise StorageError("Patch blob not found")
    return fp.read_text(encoding="utf-8", errors="replace")


def delete_patch_blob(meta: dict | None) -> None:
    if not isinstance(meta, dict):
        return
    storage = (meta.get("storage") or "").strip().lower()
    if storage == "s3":
        bucket = meta.get("bucket")
        key = meta.get("key")
        if isinstance(bucket, str) and isinstance(key, str):
            try:
                _s3_client().delete_object(Bucket=bucket, Key=key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to delete S3 patch blob", extra={"reason": str(exc)})
        return

    sha = meta.get("sha256")
    if isinstance(sha, str) and sha:
        delete_patch_blob_by_sha(sha)


def delete_patch_blob_by_sha(sha: str) -> None:
    if not isinstance(sha, str) or not sha:
        return

    fp = _local_patch_path(sha)
    base = Path(settings.db_dir).resolve()
    if base not in fp.parents and fp != base:
        logger.warning("Refusing to delete patch blob outside db_dir", extra={"sha": sha})
        return
    try:
        fp.unlink(missing_ok=True)
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
        _s3_client().delete_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete S3 patch blob", extra={"reason": str(exc)})


def get_patch_download_url(meta: dict) -> str | None:
    if not isinstance(meta, dict):
        return None
    storage = (meta.get("storage") or "").strip().lower()
    if storage != "s3":
        return None
    bucket = meta.get("bucket")
    key = meta.get("key")
    if not isinstance(bucket, str) or not isinstance(key, str):
        return None
    return _s3_signed_url(bucket, key)
