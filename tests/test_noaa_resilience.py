"""
Resilience tests for the NOAA critical habitat API layer.

Verify graceful behavior when the upstream ArcGIS service errors, times out,
truncates results, or returns malformed / geometry-less payloads. The NOAA
API catches per-layer query failures and records them as warnings rather than
raising, so a single failing layer must not abort the whole request. The
shared ArcGISService is mocked to simulate each failure mode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "noaa"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_noaa_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_noaa_resilience_api", SERVER_DIR / "src" / "apis" / "noaa_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_noaa_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _polygon_feature(*, entity="Test whale DPS", area=42.0, geometry=SIMPLE_GEOMETRY):
    feature = {
        "attributes": {
            "comname": "Test whale",
            "listentity": entity,
            "liststatus": "Endangered",
            "areasqkm": area,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


class TestUpstreamQueryFailure:
    def test_both_layers_failing_is_reported_not_raised(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("NOAA WCR upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 0
        assert any("layer query failed" in w for w in result["warnings"])
        assert any("No NOAA critical habitat layers were queried successfully" in w for w in result["warnings"])

    def test_one_layer_failing_keeps_the_other(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == 1:
                raise RuntimeError("line layer down")
            return ArcGISFeatureQueryResult(features=[_polygon_feature(area=10.0)], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 1
        assert any("Critical Habitat (Lines) layer query failed" in w for w in result["warnings"])

    def test_buffer_creation_failure_returns_error_dict(self, monkeypatch):
        api = _load_noaa_api()

        def boom(*_a, **_k):
            raise RuntimeError("buffer service unavailable")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 0
        assert result["habitats"] == []
        assert "buffer service unavailable" in result["error"]


class TestTruncationHandling:
    def test_truncation_marks_area_incomplete_and_warns(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == 2:
                return ArcGISFeatureQueryResult(
                    features=[_polygon_feature(area=42.0)],
                    warnings=["NOAA polygon layer reached the feature safety cap."],
                    truncated=True,
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        habitats, warnings = api._query_noaa_ch_layers(SIMPLE_GEOMETRY)
        assert habitats[0]["area_complete"] is False
        assert any("feature safety cap" in w for w in warnings)
        assert any("may be understated" in w for w in warnings)


class TestMissingGeometry:
    def test_missing_polygon_geometry_is_not_zero_area(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == 2:
                return ArcGISFeatureQueryResult(
                    features=[_polygon_feature(area=42.0, geometry=None)],
                    warnings=[],
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        habitats, warnings = api._query_noaa_ch_layers(SIMPLE_GEOMETRY)
        assert habitats[0]["area_sqkm"] is None
        assert habitats[0]["area_status"] == "no_geometry"
        assert habitats[0]["area_complete"] is False
        assert any("No feature polygon geometries" in w for w in warnings)


class TestMalformedFeatures:
    def test_feature_without_attributes_key_does_not_crash(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda _u, layer_id, _g, **_k: ArcGISFeatureQueryResult(
                features=[{}] if layer_id == 2 else [], warnings=[]
            ),
        )
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        # A feature with no attributes still parses to one empty-key habitat.
        assert result["total"] == 1
        assert result["habitats"][0]["listed_entity"] == ""

    def test_null_area_values_do_not_crash(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda _u, layer_id, _g, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"listentity": "Whale", "areasqkm": None}, "geometry": SIMPLE_GEOMETRY}]
                if layer_id == 2
                else [],
                warnings=[],
            ),
        )
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 1

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 0
        assert result["habitats"] == []
