import importlib

from app.config import settings


def test_async_database_url_normalization(monkeypatch) -> None:
    import app.async_db as async_db

    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pass@localhost:5432/dbname",
    )
    assert (
        async_db._async_database_url()
        == "postgresql+psycopg_async://user:pass@localhost:5432/dbname"
    )

    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@localhost:5432/dbname")
    assert async_db._async_database_url() == "postgresql+psycopg_async://user:pass@localhost:5432/dbname"

    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg_async://user:pass@localhost:5432/dbname",
    )
    assert async_db._async_database_url() == "postgresql+psycopg_async://user:pass@localhost:5432/dbname"


def test_async_engine_uses_pool_settings_from_config(monkeypatch) -> None:
    import app.async_db as async_db

    captured: dict[str, object] = {}

    def fake_create_async_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    with monkeypatch.context() as patch_ctx:
        patch_ctx.setattr(settings, "database_url", "postgresql://pool-user:pool-pass@localhost:5432/pooldb")
        patch_ctx.setattr(settings, "db_pool_size", 7)
        patch_ctx.setattr(settings, "db_max_overflow", 3)
        patch_ctx.setattr(settings, "db_pool_timeout_seconds", 12.5)
        patch_ctx.setattr(settings, "db_pool_recycle_seconds", 321.0)
        patch_ctx.setattr("sqlalchemy.ext.asyncio.create_async_engine", fake_create_async_engine)

        importlib.reload(async_db)

        assert captured["url"] == "postgresql+psycopg_async://pool-user:pool-pass@localhost:5432/pooldb"
        assert captured["kwargs"] == {
            "echo": False,
            "pool_pre_ping": True,
            "pool_size": 7,
            "max_overflow": 3,
            "pool_timeout": 12.5,
            "pool_recycle": 321.0,
        }

    importlib.reload(async_db)
