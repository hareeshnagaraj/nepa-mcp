"""
Resilience tests for the Census API layer.

Verify graceful behavior when the upstream services (TIGERweb county lookup and
the ACS profile API) error, time out, or return malformed payloads. The
``requests`` layer and the ArcGIS buffer helper are mocked to simulate each
failure mode. Follows the USACE resilience template.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "census"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}
BERNALILLO = {"NAME": "Bernalillo County", "GEOID": "35001"}
ALL_VARS = [
    "DP03_0062E",
    "DP03_0088E",
    "DP03_0128PE",
    "DP03_0134PE",
    "DP03_0009PE",
    "DP03_0008E",
    "DP03_0004E",
]


def _load_census_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_census_resilience_api",
            SERVER_DIR / "src" / "apis" / "simplified_census_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_census_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestCountyLookupFailure:
    def test_tigerweb_request_exception_becomes_status_error(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)
        import requests as req_mod

        def fake_get(url, params=None, timeout=None, **_kwargs):
            if "tigerweb" in url.lower():
                raise req_mod.exceptions.ConnectionError("tigerweb down")
            return _FakeResponse([])

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        # get_census_data_by_coordinates catches CensusError from county lookup
        # and returns a structured error result rather than raising.
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["status"] == "error"
        assert data["total_counties"] == 0
        assert "TIGERweb" in data["error_message"]

    def test_tigerweb_timeout_becomes_status_error(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)
        import requests as req_mod

        def fake_get(url, params=None, timeout=None, **_kwargs):
            if "tigerweb" in url.lower():
                raise req_mod.exceptions.Timeout("timed out")
            return _FakeResponse([])

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["status"] == "error"


class TestAcsFetchDegraded:
    def test_acs_error_yields_county_error_entry(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)
        import requests as req_mod

        def fake_get(url, params=None, timeout=None, **_kwargs):
            low = url.lower()
            if "tigerweb" in low:
                return _FakeResponse({"features": [{"attributes": BERNALILLO}]})
            # ACS profile fetch fails; _fetch_census_data swallows and returns {}.
            raise req_mod.exceptions.ConnectionError("acs down")

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        # Overall call still succeeds; county carries its own error status.
        assert data["status"] == "success"
        assert data["total_counties"] == 1
        county = data["counties"][0]
        assert county["status"] == "error"
        assert county["error_message"] == "No data returned"

    def test_acs_http_error_status_is_handled(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)

        def fake_get(url, params=None, timeout=None, **_kwargs):
            low = url.lower()
            if "tigerweb" in low:
                return _FakeResponse({"features": [{"attributes": BERNALILLO}]})
            return _FakeResponse({}, status_code=500)

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["counties"][0]["status"] == "error"


class TestMalformedPayloads:
    def test_acs_short_payload_returns_empty(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)

        def fake_get(url, params=None, timeout=None, **_kwargs):
            if "tigerweb" in url.lower():
                return _FakeResponse({"features": [{"attributes": BERNALILLO}]})
            # Only a header row, no values -> len(data) < 2.
            return _FakeResponse([["DP03_0062E", "state", "county"]])

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["counties"][0]["status"] == "error"

    def test_tigerweb_missing_features_key(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)

        def fake_get(url, params=None, timeout=None, **_kwargs):
            if "tigerweb" in url.lower():
                return _FakeResponse({})  # no "features"
            return _FakeResponse([])

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["status"] == "success"
        assert data["total_counties"] == 0

    def test_feature_without_attributes_does_not_crash(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)

        def fake_get(url, params=None, timeout=None, **_kwargs):
            if "tigerweb" in url.lower():
                return _FakeResponse({"features": [{}]})  # no attributes key
            return _FakeResponse([])

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        counties = client._get_counties(34.5, -106.5, 25.0)
        # Missing GEOID -> length < 5 -> skipped, no exception.
        assert counties == []

    def test_partial_acs_values_render_na(self, monkeypatch):
        api = _load_census_api()
        _patch_roi(api, monkeypatch)

        def fake_get(url, params=None, timeout=None, **_kwargs):
            low = url.lower()
            if "tigerweb" in low:
                return _FakeResponse({"features": [{"attributes": BERNALILLO}]})
            params = params or {}
            requested = params.get("get", "").split(",") if params.get("get") else []
            headers = requested + ["state", "county"]
            # All sentinel/invalid values.
            values = ["-888888888" for _ in requested] + ["35", "001"]
            return _FakeResponse([headers, values])

        monkeypatch.setattr(api.requests, "get", fake_get)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        county = data["counties"][0]
        assert county["status"] == "success"
        assert county["indicators"]["Median household income"] == "N/A"
