"""
Performance / scaling tests for the Census API layer.

These are hermetic (network mocked) and assert algorithmic behavior at larger
synthetic county counts: many counties are processed with a bounded per-county
API call count, results stay sorted, and parsing stays fast. They do not hit the
network, so they are deterministic in CI. Mirrors the USACE performance template.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "census"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}
DEFAULT_VALUE_MAP = {
    "DP03_0062E": "55000",
    "DP03_0088E": "30000",
    "DP03_0128PE": "12.5",
    "DP03_0134PE": "15.0",
    "DP03_0009PE": "6.2",
    "DP03_0008E": "300000",
    "DP03_0004E": "280000",
}


def _load_census_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_census_perf_api",
            SERVER_DIR / "src" / "apis" / "simplified_census_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_census_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _patch_network(api, monkeypatch, counties, counter=None):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)

    def fake_get(url, params=None, timeout=None, **_kwargs):
        params = params or {}
        low = url.lower()
        if "tigerweb" in low:
            return _FakeResponse({"features": [{"attributes": a} for a in counties]})
        if url.endswith("variables.json"):
            return _FakeResponse({"variables": {}})
        if counter is not None:
            counter["acs"] += 1
        requested = params.get("get", "").split(",") if params.get("get") else []
        headers = requested + ["state", "county"]
        values = [DEFAULT_VALUE_MAP.get(var, "-888888888") for var in requested] + ["35", "001"]
        return _FakeResponse([headers, values])

    monkeypatch.setattr(api.requests, "get", fake_get)


def _synthetic_counties(n):
    counties = []
    for i in range(n):
        geoid = f"35{i:03d}"
        counties.append({"NAME": f"County {i}", "GEOID": geoid})
    return counties


class TestManyCountiesScaling:
    def test_one_api_call_per_county(self, monkeypatch):
        api = _load_census_api()
        counter = {"acs": 0}
        counties = _synthetic_counties(50)
        _patch_network(api, monkeypatch, counties, counter=counter)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        assert data["total_counties"] == 50
        # Exactly one ACS profile fetch per county (industries disabled).
        assert counter["acs"] == 50

    def test_large_county_set_parses_quickly(self, monkeypatch):
        api = _load_census_api()
        counties = _synthetic_counties(300)
        _patch_network(api, monkeypatch, counties)
        client = api.SimplifiedCensusAPI(api_key="k")
        start = time.perf_counter()
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        elapsed = time.perf_counter() - start
        assert data["total_counties"] == 300
        # In-memory parse (mocked network) for 300 counties should be fast.
        assert elapsed < 2.0


class TestCountySorting:
    def test_counties_returned_in_stable_sorted_order(self, monkeypatch):
        api = _load_census_api()
        # Provide out-of-order GEOIDs; parser sorts by (state_fips, name).
        counties = [
            {"NAME": "County 9", "GEOID": "35009"},
            {"NAME": "County 1", "GEOID": "35001"},
            {"NAME": "County 5", "GEOID": "35005"},
        ]
        _patch_network(api, monkeypatch, counties)
        client = api.SimplifiedCensusAPI(api_key="k")
        parsed = client._get_counties(34.5, -106.5, 25.0)
        assert [c["name"] for c in parsed] == ["County 1", "County 5", "County 9"]


class TestFormatterThroughput:
    def test_summary_renders_many_counties_quickly(self, monkeypatch):
        api = _load_census_api()
        counties = _synthetic_counties(300)
        _patch_network(api, monkeypatch, counties)
        client = api.SimplifiedCensusAPI(api_key="k")
        data = client.get_census_data_by_coordinates(34.5, -106.5, 25.0)
        start = time.perf_counter()
        out = api.format_census_summary(data)
        elapsed = time.perf_counter() - start
        assert "Total Counties: 300" in out
        assert elapsed < 1.0
