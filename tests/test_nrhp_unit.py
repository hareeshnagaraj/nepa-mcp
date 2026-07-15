"""
Unit tests for the NRHP API layer (``nrhp/src/apis/nrhp_api.py``).

These exercise the pure parsing/formatting/dedup logic with the ArcGIS query
layer mocked, so no network calls are made. They follow the same dynamic
per-server import pattern used by the USACE unit tests.

The NRHP api queries a polygon layer (layer 1) first, then a point layer
(layer 0), preferring the polygon record when the same ``NRIS_Refnum`` appears
in both, and de-duplicates by ``NRIS_Refnum``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_nrhp_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "nrhp"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_nrhp_unit_api",
            server_dir / "src" / "apis" / "nrhp_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_nrhp_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, feature_map, warnings=None):
    """Route features by service_name substring.

    ``service_name`` is ``"NRHP Historic Places (Polygons)"`` for layer 1 and
    ``"NRHP Historic Places (Points)"`` for layer 0, so callers key the map by
    ``"Polygons"`` / ``"Points"``.
    """

    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


def _feature(refnum, name, **overrides):
    attrs = {
        "NRIS_Refnum": refnum,
        "RESNAME": name,
        "ResType": "Building",
        "Address": "1 Main St",
        "City": "Santa Fe",
        "County": "Santa Fe",
        "State": "NM",
        "CertDate": "1975-01-01",
        "Is_NHL": "",
        "STATUS": "Listed",
        "NARA_URL": "",
        "IS_EXTANT": "Y",
    }
    attrs.update(overrides)
    return {"attributes": attrs}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParsing:
    def test_parses_property_fields(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Polygons": [_feature("111", "Palace of the Governors", NARA_URL="https://nara/111")]},
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9, 25.0)
        assert result["total"] == 1
        prop = result["properties"][0]
        assert prop["name"] == "Palace of the Governors"
        assert prop["resource_type"] == "Building"
        assert prop["state"] == "NM"
        assert prop["nris_refnum"] == "111"
        assert prop["nara_url"] == "https://nara/111"
        assert prop["geometry_type"] == "Historic Places (Polygons)"
        assert result["center"] == {"latitude": 35.6, "longitude": -105.9}
        assert result["buffer_miles"] == 25.0

    def test_missing_resname_becomes_unknown(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"Polygons": [{"attributes": {"NRIS_Refnum": "222"}}]})
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["properties"][0]["name"] == "Unknown"

    def test_nhl_count_reflects_flagged_properties(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Polygons": [
                    _feature("1", "Landmark A", Is_NHL="X"),
                    _feature("2", "Ordinary B", Is_NHL=""),
                    _feature("3", "Landmark C", Is_NHL="X"),
                ]
            },
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 3
        assert result["nhl_count"] == 2

    def test_results_sorted_by_name(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Polygons": [_feature("1", "Zebra Hall"), _feature("2", "Alpha House")]},
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        names = [p["name"] for p in result["properties"]]
        assert names == ["Alpha House", "Zebra Hall"]

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 0
        assert result["properties"] == []
        assert result["nhl_count"] == 0


# ---------------------------------------------------------------------------
# De-duplication across the two layers
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_refnum_prefers_polygon_record(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        # Same NRIS_Refnum in both layers; polygon (queried first) should win.
        _patch_query(
            api,
            monkeypatch,
            {
                "Polygons": [_feature("999", "Polygon Name")],
                "Points": [_feature("999", "Point Name")],
            },
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 1
        prop = result["properties"][0]
        assert prop["name"] == "Polygon Name"
        assert prop["geometry_type"] == "Historic Places (Polygons)"

    def test_distinct_refnums_from_both_layers_kept(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Polygons": [_feature("A", "Poly Only")],
                "Points": [_feature("B", "Point Only")],
            },
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 2
        by_name = {p["name"]: p for p in result["properties"]}
        assert by_name["Poly Only"]["geometry_type"] == "Historic Places (Polygons)"
        assert by_name["Point Only"]["geometry_type"] == "Historic Places (Points)"

    def test_blank_refnums_are_not_deduplicated(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        # Empty refnums bypass the seen-set, so both are retained.
        _patch_query(
            api,
            monkeypatch,
            {"Polygons": [_feature("", "One"), _feature("", "Two")]},
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 2


# ---------------------------------------------------------------------------
# Buffer creation failure branch
# ---------------------------------------------------------------------------


class TestBufferFailure:
    def test_buffer_failure_returns_error_dict(self, monkeypatch):
        api = _load_nrhp_api()

        def boom(*_a, **_k):
            raise RuntimeError("geometry service down")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 0
        assert result["properties"] == []
        assert result["error"] == "geometry service down"


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def test_summary_renders_properties_grouped_by_state(self, monkeypatch):
        api = _load_nrhp_api()
        data = {
            "center": {"latitude": 35.6, "longitude": -105.9},
            "buffer_miles": 25.0,
            "total": 2,
            "nhl_count": 1,
            "properties": [
                {
                    "name": "Palace of the Governors",
                    "resource_type": "Building",
                    "city": "Santa Fe",
                    "county": "Santa Fe",
                    "state": "NM",
                    "cert_date": "1960",
                    "is_nhl": "X",
                    "nara_url": "https://nara/1",
                },
                {
                    "name": "Old Fort",
                    "resource_type": "Site",
                    "city": "Taos",
                    "county": "Taos",
                    "state": "NM",
                    "cert_date": "",
                    "is_nhl": "",
                    "nara_url": "",
                },
            ],
            "warnings": [],
        }
        out = api.format_nrhp_summary(data)
        assert "National Register of Historic Places" in out
        assert "Total NRHP Properties:** 2" in out
        assert "National Historic Landmarks (NHL):** 1" in out
        assert "### NM (2 properties)" in out
        assert "Palace of the Governors" in out
        assert "🏛️ **NHL**" in out
        assert "[NARA Record](https://nara/1)" in out
        assert "36 CFR Part 800" in out

    def test_summary_handles_empty(self, monkeypatch):
        api = _load_nrhp_api()
        data = {
            "center": {"latitude": 35.6, "longitude": -105.9},
            "buffer_miles": 25.0,
            "total": 0,
            "nhl_count": 0,
            "properties": [],
            "warnings": [],
        }
        out = api.format_nrhp_summary(data)
        assert "No NRHP-listed properties were identified within the ROI buffer." in out
        assert "architectural historian" in out

    def test_summary_surfaces_error(self, monkeypatch):
        api = _load_nrhp_api()
        data = {
            "center": {"latitude": 35.6, "longitude": -105.9},
            "buffer_miles": 25.0,
            "total": 0,
            "nhl_count": 0,
            "properties": [],
            "error": "buffer failed",
        }
        out = api.format_nrhp_summary(data)
        assert "Error during query: buffer failed" in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_nrhp_api()
        data = {
            "center": {"latitude": 35.6, "longitude": -105.9},
            "buffer_miles": 25.0,
            "total": 0,
            "nhl_count": 0,
            "properties": [],
            "warnings": ["upstream degraded"],
        }
        out = api.format_nrhp_summary(data)
        assert "Warning: upstream degraded" in out
