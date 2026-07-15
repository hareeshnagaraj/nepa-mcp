"""
Unit tests for the tigerweb_counties API layer
(``tigerweb_counties/src/apis/counties_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS query layer
mocked, so no network calls are made. They follow the same dynamic per-server
import pattern used by the USACE unit tests.
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


def _load_counties_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "tigerweb_counties"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_counties_unit_api",
            server_dir / "src" / "apis" / "counties_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_counties_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_features(api, monkeypatch, features, warnings=None):
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=warnings or []),
    )


# ---------------------------------------------------------------------------
# County parsing
# ---------------------------------------------------------------------------


class TestCountyParsing:
    def test_parses_county_fields(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        _patch_features(
            api,
            monkeypatch,
            [
                {
                    "attributes": {
                        "NAME": "Bernalillo County",
                        "STATE": "35",
                        "BASENAME": "Bernalillo",
                        "LSADC": "06",
                        "GEOID": "35001",
                        "CENTLAT": "35.05",
                        "CENTLON": "-106.67",
                    }
                }
            ],
        )
        result = api.get_counties_in_roi(35.05, -106.67, 25.0)
        assert result["total_counties"] == 1
        county = result["counties"][0]
        assert county["name"] == "Bernalillo County"
        assert county["state"] == "35"
        assert county["basename"] == "Bernalillo"
        assert county["type"] == "06"
        assert county["fips"] == "35001"
        assert county["centroid_lat"] == "35.05"
        assert county["centroid_lon"] == "-106.67"
        assert result["center"] == {"latitude": 35.05, "longitude": -106.67}
        assert result["buffer_miles"] == 25.0

    def test_unknown_name_when_field_missing(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        _patch_features(api, monkeypatch, [{"attributes": {}}])
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 1
        county = result["counties"][0]
        assert county["name"] == "Unknown"
        assert county["state"] == ""
        assert county["fips"] == ""

    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        _patch_features(api, monkeypatch, [{}])
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 1
        assert result["counties"][0]["name"] == "Unknown"

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        _patch_features(api, monkeypatch, [])
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 0
        assert result["counties"] == []


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestSorting:
    def test_counties_sorted_by_state_then_name(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        _patch_features(
            api,
            monkeypatch,
            [
                {"attributes": {"NAME": "Zebra County", "STATE": "04", "GEOID": "04099"}},
                {"attributes": {"NAME": "Apple County", "STATE": "04", "GEOID": "04001"}},
                {"attributes": {"NAME": "Alpha County", "STATE": "01", "GEOID": "01001"}},
            ],
        )
        result = api.get_counties_in_roi(34.5, -106.5)
        ordered = [(c["state"], c["name"]) for c in result["counties"]]
        assert ordered == [
            ("01", "Alpha County"),
            ("04", "Apple County"),
            ("04", "Zebra County"),
        ]


# ---------------------------------------------------------------------------
# Warnings passthrough
# ---------------------------------------------------------------------------


class TestWarnings:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        _patch_features(
            api,
            monkeypatch,
            [{"attributes": {"NAME": "Bernalillo County", "STATE": "35"}}],
            warnings=["reached the feature safety cap; results are partial."],
        )
        result = api.get_counties_in_roi(34.5, -106.5)
        assert any("safety cap" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def test_summary_renders_markdown(self, monkeypatch):
        api = _load_counties_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_counties": 1,
            "counties": [
                {"name": "Bernalillo County", "state": "35", "fips": "35001"},
            ],
            "warnings": [],
        }
        out = api.format_counties_summary(data)
        assert "Counties within ROI" in out
        assert "Total Counties: 1" in out
        assert "Bernalillo County" in out
        assert "FIPS: 35001" in out

    def test_summary_handles_empty(self, monkeypatch):
        api = _load_counties_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_counties": 0,
            "counties": [],
            "warnings": [],
        }
        out = api.format_counties_summary(data)
        assert "No counties found within the ROI." in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_counties_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_counties": 0,
            "counties": [],
            "warnings": ["upstream degraded"],
        }
        out = api.format_counties_summary(data)
        assert "Warning: upstream degraded" in out
