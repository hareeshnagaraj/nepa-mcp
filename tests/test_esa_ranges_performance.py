"""
Performance / scaling tests for the esa_ranges API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: (listed_entity, huc12) deduplication collapses many
diced fragments to few unique records, Layer-1 repeated-HUC areas are not
multiplied, and parsing stays bounded in time. They do not hit the network, so
they are deterministic in CI. Geometry is omitted from the synthetic features so
timing reflects parsing/dedup rather than the shapely clip.
"""

from __future__ import annotations

import importlib.util
import sys
import time
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
            "_esa_perf_api", server_dir / "src" / "apis" / "esa_ranges_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_esa_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_layers(api, monkeypatch, layer_features):
    def query_features(_url, layer_id, _geometry, **_kwargs):
        return ArcGISFeatureQueryResult(features=layer_features.get(layer_id, []), warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


def _l2(listentity, huc12):
    # No geometry -> exercises pure dedup/parse without the shapely clip.
    return {"attributes": {"listentity": listentity, "huc12": huc12, "areasqkm": 1.0, "sciename": "3"}}


class TestDeduplicationScaling:
    def test_many_fragments_collapse_by_entity_and_huc(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        # 1000 fragments across 10 distinct (entity, huc) keys.
        entities = ["CKCAC" for _ in range(1000)]
        features = [_l2(entities[i], f"HUC{i % 10:012d}") for i in range(1000)]
        _patch_layers(api, monkeypatch, {_LAYER2_ID: features, _LAYER1_ID: []})
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 10
        assert result["watershed_count"] == 10

    def test_distinct_entities_are_counted(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        # 500 features: 5 entities x same huc -> 5 unique records (distinct entity).
        features = [_l2(f"ENT{i % 5}", "HUC000000000001") for i in range(500)]
        _patch_layers(api, monkeypatch, {_LAYER2_ID: features, _LAYER1_ID: []})
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 5
        assert result["species_count"] == 5


class TestLayer1AreaScaling:
    def test_repeated_huc_area_not_multiplied_at_scale(self):
        api = _load_esa_api()
        base = {
            "dps": "Steelhead (Puget Sound DPS)",
            "dps_id": "STPUG",
            "species": "ST",
            "hydrologic_huc_12": "171100020101",
            "hydrologic_hu_12_name": "Puget Sound",
            "hydrologic_hu_area_sqkm": 42.5,
        }
        features = [{"attributes": {**base, "population": f"P{i}"}} for i in range(500)]
        record = api._normalize_layer1(features)[0]
        # max() over 500 identical values, not a sum.
        assert record["source_area_sqkm"] == 42.5


class TestParsingThroughput:
    def test_large_fragment_set_dedups_quickly(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        # 5000 diced fragments collapsing to 10 unique (entity, huc) keys. The
        # ROI clip runs once per unique record, so dedup keeps this bounded.
        features = [_l2(f"ENT{i % 10}", f"HUC{i % 10:012d}") for i in range(5000)]
        _patch_layers(api, monkeypatch, {_LAYER2_ID: features, _LAYER1_ID: []})
        start = time.perf_counter()
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        elapsed = time.perf_counter() - start
        assert result["total"] == 10
        # 5k-fragment parse + 10 clips should be well under a couple seconds.
        assert elapsed < 2.0

    def test_both_layers_merge_bounded(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        # Many fragments per layer collapsing to 50 shared keys -> Layer 2 wins.
        layer2 = [_l2(f"ENT{i % 50}", f"HUC{i % 50:012d}") for i in range(1000)]
        layer1 = [
            {
                "attributes": {
                    "dps": f"ENT{i % 50}",
                    "dps_id": "STPUG",
                    "species": "ST",
                    "hydrologic_huc_12": f"HUC{i % 50:012d}",
                    "hydrologic_hu_area_sqkm": 1.0,
                }
            }
            for i in range(1000)
        ]
        _patch_layers(api, monkeypatch, {_LAYER2_ID: layer2, _LAYER1_ID: layer1})
        start = time.perf_counter()
        result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)
        elapsed = time.perf_counter() - start
        # Same 50 keys in both layers -> Layer 2 wins, 50 merged records.
        assert result["total"] == 50
        assert elapsed < 2.0
