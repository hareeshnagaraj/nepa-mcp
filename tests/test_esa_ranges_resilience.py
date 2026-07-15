"""
Resilience tests for the esa_ranges API layer.

Verify graceful behavior when one of the two Ranges_dice layers errors while the
other succeeds, when results are truncated (area marked incomplete), when
geometry is missing, and when the ArcGIS buffer step fails. The per-layer
``_query_layer`` helper swallows a single layer's exception into a warning so the
complementary layer can still return; a buffer-creation failure short-circuits to
an ``error`` result.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}

_LAYER2_ID = 2
_LAYER1_ID = 1


def _load_esa_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "esa_ranges"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_esa_resilience_api", server_dir / "src" / "apis" / "esa_ranges_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_esa_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _layer2_feature(*, listentity="STUCR", huc12="170200160601", area=999.0, geometry=SIMPLE_GEOMETRY):
    feature = {
        "attributes": {
            "listentity": listentity,
            "liststatus": "T",
            "sciename": "3",
            "comname": "ST",
            "taxon": "3",
            "leadoffice": "WCR",
            "areasqkm": area,
            "huc12": huc12,
            "huc12_name": "Parsons Canyon-Columbia River",
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


class TestBufferCreationFailure:
    def test_buffer_failure_returns_error_result(self, monkeypatch):
        api = _load_esa_api()

        def boom(*_a, **_k):
            raise RuntimeError("buffer service down")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 0
        assert result["species"] == []
        assert "buffer service down" in result["error"]


class TestOneLayerFailsOtherSucceeds:
    def test_layer2_fails_layer1_still_returns(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        layer1 = {
            "attributes": {
                "dps": "Steelhead (Puget Sound DPS)",
                "dps_id": "STPUG",
                "species": "ST",
                "listing_status": "T",
                "hydrologic_huc_12": "171100020101",
                "hydrologic_hu_12_name": "Puget Sound",
                "hydrologic_hu_area_sqkm": 42.5,
            },
            "geometry": SIMPLE_GEOMETRY,
        }

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == _LAYER2_ID:
                raise RuntimeError("Layer 2 upstream 500")
            return ArcGISFeatureQueryResult(features=[layer1], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_esa_species_ranges_in_roi(48.94, -122.93, 5.0)
        # Layer-1 record survives; the failed layer is reported as a warning.
        assert result["total"] == 1
        assert result["species"][0]["listed_entity"] == "Steelhead (Puget Sound DPS)"
        assert any("Layer 2 upstream 500" in w for w in result["warnings"])

    def test_layer1_fails_layer2_still_returns(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == _LAYER1_ID:
                raise RuntimeError("Layer 1 upstream 500")
            return ArcGISFeatureQueryResult(features=[_layer2_feature()], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 1
        assert any("Layer 1 upstream 500" in w for w in result["warnings"])

    def test_both_layers_fail_yields_zero_with_warnings(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("all down")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 0
        assert len([w for w in result["warnings"] if "all down" in w]) == 2


class TestTruncation:
    def test_truncation_marks_area_incomplete(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == _LAYER2_ID:
                return ArcGISFeatureQueryResult(
                    features=[_layer2_feature()],
                    warnings=["reached the feature safety cap; results are partial."],
                    truncated=True,
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["species"][0]["area_complete"] is False
        assert any("may be understated" in w for w in result["warnings"])
        assert any("safety cap" in w for w in result["warnings"])


class TestMalformedFeatures:
    def test_missing_geometry_is_no_geometry_status(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == _LAYER2_ID:
                return ArcGISFeatureQueryResult(features=[_layer2_feature(geometry=None)], warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        record = result["species"][0]
        assert record["area_sqkm"] is None
        assert record["area_status"] == "no_geometry"
        assert record["area_complete"] is False

    def test_feature_without_attributes_does_not_crash(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == _LAYER2_ID:
                return ArcGISFeatureQueryResult(features=[{}], warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        # An attribute-less feature parses to an empty-keyed "Unknown" record.
        assert result["total"] == 1
        assert result["species"][0]["listed_entity"] == ""

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == _LAYER2_ID:
                return ArcGISFeatureQueryResult(
                    features=[{"attributes": {"listentity": None, "huc12": None, "areasqkm": None}}],
                    warnings=[],
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 1


class TestCoverageWarning:
    def test_out_of_coverage_empty_result_is_flagged(self, monkeypatch):
        api = _load_esa_api()
        # An ROI far from the West Coast (Chicago-ish) with no results.
        chicago = {
            "rings": [[[-88.0, 41.5], [-87.0, 41.5], [-87.0, 42.0], [-88.0, 42.0], [-88.0, 41.5]]],
            "spatialReference": {"wkid": 4326},
        }
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: chicago)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_esa_species_ranges_in_roi(41.8, -87.6, 5.0)
        assert result.get("outside_expected_coverage") is True
        assert "coverage_warning" in result
