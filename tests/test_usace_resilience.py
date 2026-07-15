"""
Resilience tests for the USACE API layer.

Verify graceful behavior when the upstream ArcGIS service errors, times out,
returns malformed payloads, or truncates results. The shared ArcGISService is
mocked to simulate each failure mode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_usace_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "usace"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_usace_resilience_api", server_dir / "src" / "apis" / "usace_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_usace_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestUpstreamQueryFailure:
    def test_query_raises_bubbles_up(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("USACE Regulatory Boundary upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        with pytest.raises(RuntimeError):
            api.get_usace_regulatory_district(34.5, -106.5)

    def test_timeout_bubbles_up(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        with pytest.raises(req_mod.exceptions.Timeout):
            api.get_wetland_regions_in_roi(34.5, -106.5)


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)

        def query_features(*_a, **_k):
            return ArcGISFeatureQueryResult(
                features=[{"attributes": {"ERO_FORMALNAME": "Albuquerque District"}}],
                warnings=["reached the feature safety cap; results are partial."],
                truncated=True,
            )

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_usace_regulatory_district(34.5, -106.5)
        assert result["total_districts"] == 1
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_wetland_subregions_in_roi(34.5, -106.5)
        assert result["total_subregions"] == 0
        assert result["subregions"] == []


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        result = api.get_usace_regulatory_district(34.5, -106.5)
        # A feature with no attributes should still parse to an "Unknown" district.
        assert result["total_districts"] == 1
        assert result["districts"][0]["district_name"] == "Unknown"

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"REGION": None, "MLRA_NAME": None}}], warnings=[]
            ),
        )
        result = api.get_wetland_regions_in_roi(34.5, -106.5)
        assert result["total_regions"] == 1


class TestComprehensivePartialFailure:
    def test_one_dataset_failing_raises(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, _layer_id, _geometry, *, service_name=None, **_k):
            if "Subregions" in (service_name or "") or "subregions" in url:
                raise RuntimeError("subregions service down")
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        # analyze_usace_jurisdiction calls all three; a hard failure in one bubbles up.
        with pytest.raises(RuntimeError):
            api.analyze_usace_jurisdiction(34.5, -106.5)
