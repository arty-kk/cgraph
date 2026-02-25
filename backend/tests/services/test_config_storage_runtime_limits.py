import sys
import tempfile
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import Settings


def test_presign_limit_falls_back_to_legacy_signed_url_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUBGRAPH_S3_SIGNED_URL_CONCURRENCY_LIMIT", "3")
    monkeypatch.delenv("STUBGRAPH_S3_PRESIGN_CONCURRENCY_LIMIT", raising=False)

    cfg = Settings()

    assert cfg.s3_signed_url_concurrency_limit == 3
    assert cfg.s3_presign_concurrency_limit == 3


def test_presign_limit_uses_explicit_new_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUBGRAPH_S3_SIGNED_URL_CONCURRENCY_LIMIT", "3")
    monkeypatch.setenv("STUBGRAPH_S3_PRESIGN_CONCURRENCY_LIMIT", "5")

    cfg = Settings()

    assert cfg.s3_signed_url_concurrency_limit == 3
    assert cfg.s3_presign_concurrency_limit == 5


def test_presign_limit_from_env_file_overrides_legacy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "STUBGRAPH_S3_SIGNED_URL_CONCURRENCY_LIMIT=3",
                    "STUBGRAPH_S3_PRESIGN_CONCURRENCY_LIMIT=5",
                ]
            ),
            encoding="utf-8",
        )

        cfg = Settings(_env_file=str(env_path))

    assert cfg.s3_signed_url_concurrency_limit == 3
    assert cfg.s3_presign_concurrency_limit == 5


def test_presign_limit_explicit_default_value_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUBGRAPH_S3_SIGNED_URL_CONCURRENCY_LIMIT", "3")
    monkeypatch.setenv("STUBGRAPH_S3_PRESIGN_CONCURRENCY_LIMIT", "8")

    cfg = Settings()

    assert cfg.s3_signed_url_concurrency_limit == 3
    assert cfg.s3_presign_concurrency_limit == 8


def test_scan_runtime_limits_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUBGRAPH_SCAN_STAGE_BATCH_SIZE", "0")
    with pytest.raises(ValueError, match="STUBGRAPH_SCAN_STAGE_BATCH_SIZE"):
        Settings()


def test_scan_runtime_limits_loaded_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUBGRAPH_SCAN_STAGE_BATCH_SIZE", "12")
    monkeypatch.setenv("STUBGRAPH_SCAN_STAGE_MAX_PARALLEL", "5")
    monkeypatch.setenv("STUBGRAPH_SCAN_EMBEDDINGS_MAX_PARALLEL", "3")

    cfg = Settings()

    assert cfg.scan_stage_batch_size == 12
    assert cfg.scan_stage_max_parallel == 5
    assert cfg.scan_embeddings_max_parallel == 3
