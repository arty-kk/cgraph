import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import routing_calibration_service


@pytest.mark.anyio
async def test_derive_thresholds_async_uses_run_cpu_io_async(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return (1.1, 1.3, 1.6)

    monkeypatch.setattr(routing_calibration_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await routing_calibration_service._derive_thresholds_async(
        defaults=(1.2, 1.4, 1.7),
        rows=[],
    )

    assert result == (1.1, 1.3, 1.6)
    assert captured["func"] is routing_calibration_service._derive_thresholds
    assert captured["kwargs"] == {
        "defaults": (1.2, 1.4, 1.7),
        "rows": [],
        "operation": "routing_calibration.derive_thresholds",
    }


@pytest.mark.anyio
async def test_derive_base_weights_async_uses_run_cpu_io_async(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"quality": 0.4, "latency": 0.3, "token_cost": 0.2, "fail_rate": 0.1}

    monkeypatch.setattr(routing_calibration_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await routing_calibration_service._derive_base_weights_async(
        defaults={"quality": 0.5, "latency": 0.2, "token_cost": 0.2, "fail_rate": 0.1},
        rows=[],
    )

    assert result == {"quality": 0.4, "latency": 0.3, "token_cost": 0.2, "fail_rate": 0.1}
    assert captured["func"] is routing_calibration_service._derive_base_weights
    assert captured["kwargs"] == {
        "defaults": {"quality": 0.5, "latency": 0.2, "token_cost": 0.2, "fail_rate": 0.1},
        "rows": [],
        "operation": "routing_calibration.derive_base_weights",
    }


@pytest.mark.anyio
async def test_build_profile_weights_async_uses_run_cpu_io_async(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"balanced": {"quality": 0.4, "latency": 0.3, "token_cost": 0.2, "fail_rate": 0.1}}

    monkeypatch.setattr(routing_calibration_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await routing_calibration_service._build_profile_weights_async(
        {"quality": 0.4, "latency": 0.3, "token_cost": 0.2, "fail_rate": 0.1}
    )

    assert result == {
        "balanced": {"quality": 0.4, "latency": 0.3, "token_cost": 0.2, "fail_rate": 0.1}
    }
    assert captured["func"] is routing_calibration_service._build_profile_weights
    assert captured["args"] == (
        {"quality": 0.4, "latency": 0.3, "token_cost": 0.2, "fail_rate": 0.1},
    )
    assert captured["kwargs"] == {"operation": "routing_calibration.build_profile_weights"}


@pytest.mark.anyio
async def test_store_profile_weight_async_writes_cache(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_cache_set_json_async(key, payload):
        captured["key"] = key
        captured["payload"] = payload

    monkeypatch.setattr(
        routing_calibration_service,
        "cache_set_json_async",
        _fake_cache_set_json_async,
    )

    await routing_calibration_service._store_profile_weight_async(
        version="v1",
        sla_profile="fast",
        weights={"quality": 0.3, "latency": 0.4, "token_cost": 0.2, "fail_rate": 0.1},
        samples=123,
        updated_at="2026-01-01T00:00:00Z",
    )

    assert captured["key"] == ["routing_policy", "weights", "v1", "fast"]
    assert captured["payload"] == {
        "version": "v1",
        "policy_version": "v1",
        "sla_profile": "fast",
        "weights": {"quality": 0.3, "latency": 0.4, "token_cost": 0.2, "fail_rate": 0.1},
        "samples": 123,
        "updated_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.anyio
async def test_store_thresholds_async_writes_cache(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_cache_set_json_async(key, payload):
        captured["key"] = key
        captured["payload"] = payload

    monkeypatch.setattr(
        routing_calibration_service,
        "cache_set_json_async",
        _fake_cache_set_json_async,
    )

    payload = {"version": "v1", "low": 1.2, "mid": 1.4, "high": 1.6, "samples": 10}
    await routing_calibration_service._store_thresholds_async(
        version="v1",
        thresholds_payload=payload,
    )

    assert captured["key"] == ["routing_policy", "thresholds", "v1"]
    assert captured["payload"] == payload
