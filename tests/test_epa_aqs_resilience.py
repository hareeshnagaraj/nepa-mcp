"""
Resilience tests for the EPA AQS API layer.

Verify graceful behavior when the upstream EPA AQS HTTP service errors, times
out, returns malformed payloads, or returns "no data" statuses. The synchronous
HTTP call (``requests.get``) and the ArcGIS buffer service are mocked to
simulate each mode. Async helpers are driven with ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}
BBOX = {"minlat": 34.0, "maxlat": 35.0, "minlon": -107.0, "maxlon": -106.0}


def _load_aqs_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_test_epa_"):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "epa_aqs"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    module_path = server_dir / "src" / "apis" / "aqs_api.py"
    spec = importlib.util.spec_from_file_location("_test_epa_aqs_api", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_epa_aqs_api"] = module
    spec.loader.exec_module(module)
    return module


def _set_creds(monkeypatch):
    monkeypatch.setenv("EPA_AQS_EMAIL", "test@example.com")
    monkeypatch.setenv("EPA_AQS_API_KEY", "test-aqs-key")


class _FakeResponse:
    def __init__(self, payload, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# HTTP layer error handling in _query_aqs_api_sync
# ---------------------------------------------------------------------------


class TestSyncQueryErrors:
    def test_http_error_wrapped_in_aqs_error(self, monkeypatch):
        api = _load_aqs_api()
        import requests as req_mod

        def get(*_a, **_k):
            return _FakeResponse({}, status_error=req_mod.exceptions.HTTPError("500 boom"))

        monkeypatch.setattr(api.requests, "get", get)
        with pytest.raises(api.AQSAPIError):
            api._query_aqs_api_sync("http://x", {})

    def test_api_header_error_status_raises(self, monkeypatch):
        api = _load_aqs_api()
        payload = {"Header": [{"status": "Failed", "error": "bad param"}], "Data": []}
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(payload))
        with pytest.raises(api.AQSAPIError):
            api._query_aqs_api_sync("http://x", {})

    def test_no_data_status_is_not_an_error(self, monkeypatch):
        api = _load_aqs_api()
        payload = {"Header": [{"status": "No data matched your selection"}], "Data": []}
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(payload))
        data = api._query_aqs_api_sync("http://x", {})
        assert data["Data"] == []

    def test_timeout_retries_then_raises(self, monkeypatch):
        api = _load_aqs_api()
        import requests as req_mod

        def always_timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.requests, "get", always_timeout)
        monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)
        with pytest.raises(api.AQSAPIError):
            api._query_aqs_api_sync("http://x", {}, max_retries=2)


# ---------------------------------------------------------------------------
# Async gather tolerance
# ---------------------------------------------------------------------------


class TestAsyncGatherTolerance:
    def test_all_params_failing_returns_empty(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def boom(*_a, **_k):
            raise api.AQSAPIError("down")

        monkeypatch.setattr(api, "_query_aqs_api_sync", boom)
        monitors = asyncio.run(api.get_monitors_by_box(BBOX, "20240101", "20241231", ["88101", "85101"]))
        assert monitors == []

    def test_annual_partial_failure_keeps_good_records(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)

        def fake_sync(_endpoint, params, max_retries=3):
            if params["param"] == "85101":
                raise api.AQSAPIError("down")
            return {"Data": [{"parameter_code": params["param"], "arithmetic_mean": "5.0"}]}

        monkeypatch.setattr(api, "_query_aqs_api_sync", fake_sync)
        data = asyncio.run(api.get_annual_data_by_box(BBOX, 2024, 2024, ["88101", "85101"]))
        assert len(data) == 1


# ---------------------------------------------------------------------------
# Malformed / degraded payloads in parsing
# ---------------------------------------------------------------------------


class TestMalformedData:
    def test_missing_data_key_yields_no_monitors(self, monkeypatch):
        api = _load_aqs_api()
        _set_creds(monkeypatch)
        monkeypatch.setattr(api, "RATE_LIMIT_SECONDS", 0.0)
        monkeypatch.setattr(api, "_query_aqs_api_sync", lambda *_a, **_k: {})
        monitors = asyncio.run(api.get_monitors_by_box(BBOX, "20240101", "20241231", ["88101"]))
        assert monitors == []

    def test_records_with_missing_fields_do_not_crash(self):
        api = _load_aqs_api()
        # No arithmetic_mean anywhere for a valid pollutant -> pollutant dropped.
        result = api.assess_naaqs_compliance([{"parameter_code": "88101", "site_number": "001"}])
        assert result == {}

    def test_unknown_parameter_code_is_ignored(self):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [{"parameter_code": "99999", "arithmetic_mean": "1.0", "site_number": "001"}]
        )
        assert result == {}

    def test_none_max_value_handled(self):
        api = _load_aqs_api()
        result = api.assess_naaqs_compliance(
            [{"parameter_code": "88101", "arithmetic_mean": "5.0", "first_max_value": None, "site_number": "001"}]
        )
        assert result["PM2.5"]["max_value"] is None
