"""
Resilience tests for the FEMA NFHL API layer.

Verify graceful behavior when the upstream FEMA MapServer errors, times out,
returns malformed payloads, or truncates results. The ``requests.get`` call is
mocked to simulate each failure mode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "fema_nfhl"

FLOOD_ZONES_LAYER = 28


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def _load_fema_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_fema_res_"):
            sys.modules.pop(module_name, None)
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    module_path = SERVER_DIR / "src" / "apis" / "fema_nfhl_api.py"
    spec = importlib.util.spec_from_file_location("_fema_res_api", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fema_res_api"] = module
    spec.loader.exec_module(module)
    return module


class TestUpstreamQueryFailure:
    def test_request_exception_is_wrapped(self, monkeypatch):
        fema_api = _load_fema_api()

        def boom(*_a, **_k):
            raise fema_api.requests.exceptions.ConnectionError("upstream 500")

        monkeypatch.setattr(fema_api.requests, "get", boom)
        # RequestException is caught and re-raised as RuntimeError.
        with pytest.raises(RuntimeError):
            fema_api.get_flood_zones(29.95, -90.07)

    def test_timeout_is_wrapped(self, monkeypatch):
        fema_api = _load_fema_api()

        def timeout(*_a, **_k):
            raise fema_api.requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(fema_api.requests, "get", timeout)
        with pytest.raises(RuntimeError):
            fema_api.get_levees(29.95, -90.07)

    def test_api_error_payload_raises(self, monkeypatch):
        fema_api = _load_fema_api()

        def error_payload(*_a, **_k):
            return _FakeResponse({"error": {"message": "Invalid layer"}})

        monkeypatch.setattr(fema_api.requests, "get", error_payload)
        with pytest.raises(RuntimeError):
            fema_api.get_flood_zones(29.95, -90.07)


class TestMalformedPayloads:
    def test_non_list_features_raises(self, monkeypatch):
        fema_api = _load_fema_api()

        def malformed(*_a, **_k):
            return _FakeResponse({"features": "not-a-list"})

        monkeypatch.setattr(fema_api.requests, "get", malformed)
        with pytest.raises(RuntimeError):
            fema_api.get_flood_zones(29.95, -90.07)

    def test_missing_features_key_is_empty(self, monkeypatch):
        fema_api = _load_fema_api()

        def no_features(*_a, **_k):
            return _FakeResponse({})

        monkeypatch.setattr(fema_api.requests, "get", no_features)
        result = fema_api.get_flood_zones(29.95, -90.07)
        assert result["total_zones"] == 0

    def test_feature_without_attributes_does_not_crash(self, monkeypatch):
        fema_api = _load_fema_api()

        def missing_attrs(*_a, **_k):
            return _FakeResponse({"exceededTransferLimit": False, "features": [{}]})

        monkeypatch.setattr(fema_api.requests, "get", missing_attrs)
        result = fema_api.get_flood_zones(29.95, -90.07)
        assert result["total_zones"] == 1
        assert result["summary"]["zone_counts"] == {"Unknown": 1}


class TestDegradedButUsable:
    def test_empty_features_is_not_an_error(self, monkeypatch):
        fema_api = _load_fema_api()

        def empty(*_a, **_k):
            return _FakeResponse({"exceededTransferLimit": False, "features": []})

        monkeypatch.setattr(fema_api.requests, "get", empty)
        result = fema_api.get_water_areas(29.95, -90.07)
        assert result["total_water_areas"] == 0
        assert result["water_areas"] == []

    def test_truncation_warning_surfaces(self, monkeypatch):
        fema_api = _load_fema_api()

        def exceeded(*_a, **_k):
            return _FakeResponse(
                {
                    "exceededTransferLimit": True,
                    "features": [{"attributes": {"OBJECTID": 1}}, {"attributes": {"OBJECTID": 2}}],
                }
            )

        monkeypatch.setattr(fema_api.requests, "get", exceeded)
        result = fema_api._query_nfhl_layer_result(FLOOD_ZONES_LAYER, 29.95, -90.07, radius_miles=10, max_features=2)
        assert result.truncated is True
        assert any("reached max_features" in w for w in result.warnings)


class TestScreeningPartialFailure:
    def test_flood_layer_failure_bubbles_up(self, monkeypatch):
        fema_api = _load_fema_api()

        def boom(*_a, **_k):
            raise fema_api.requests.exceptions.ConnectionError("flood layer down")

        monkeypatch.setattr(fema_api.requests, "get", boom)
        # analyze_flood_risk queries flood zones first; a hard failure bubbles up.
        with pytest.raises(RuntimeError):
            fema_api.analyze_flood_risk(29.95, -90.07)
