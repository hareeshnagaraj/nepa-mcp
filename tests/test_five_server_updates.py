from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult
from nepa_mcp_common.validation import (
    NOAA_WEST_COAST_EXPECTED_BOUNDS,
    add_empty_result_coverage_warning,
)


ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_api(server_name: str):
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)

    server_dir = ROOT / server_name
    sys.path.insert(0, str(server_dir))
    try:
        module_name = f"_five_server_updates_{server_name}"
        spec = importlib.util.spec_from_file_location(
            module_name,
            server_dir / "src" / "apis" / f"{server_name}_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def test_esa_ranges_queries_both_layers_and_layer2_wins(monkeypatch) -> None:
    api = _load_api("esa_ranges")
    calls: list[int] = []

    layer1 = {
        "attributes": {
            "dps": "Steelhead (Upper Columbia River DPS)",
            "dps_id": "STUCR",
            "species": "ST",
            "listing_status": "T",
            "hydrologic_huc_12": "170200160601",
            "hydrologic_hu_12_name": "Parsons Canyon-Columbia River",
            "hydrologic_hu_area_sqkm": 232.27,
            "link_feature_access": "AC",
        }
    }
    layer2 = {
        "attributes": {
            "listentity": "STUCR",
            "liststatus": "T",
            "sciename": "3",
            "comname": "ST",
            "taxon": "3",
            "leadoffice": "WCR",
            "areasqkm": 999.0,
            "huc12": "170200160601",
            "huc12_name": "Parsons Canyon-Columbia River",
            "feature_access": "AC",
            "notes": "layer-2-authoritative",
        }
    }

    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: SIMPLE_GEOMETRY)

    def query_features(_url, layer_id, _geometry, **_kwargs):
        calls.append(layer_id)
        features = [layer2] if layer_id == api.ESA_RANGES_LAYER_ID else [layer1]
        return ArcGISFeatureQueryResult(features=features, warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)

    result = api.get_esa_species_ranges_in_roi(46.47, -119.30, 5.0)

    assert calls == [api.ESA_RANGES_LAYER_ID, api.ESA_RANGES_FISH_LAYER_ID]
    assert result["total"] == 1
    assert result["species"][0]["listed_entity"] == "Steelhead (Upper Columbia River DPS)"
    assert result["species"][0]["notes"] == "layer-2-authoritative"
    assert result["species"][0]["area_sqkm"] == 999.0


def test_esa_ranges_keeps_layer1_only_wa_record(monkeypatch) -> None:
    api = _load_api("esa_ranges")
    layer1 = {
        "attributes": {
            "dps": "Steelhead (Puget Sound DPS)",
            "dps_id": "STPUG",
            "species": "ST",
            "listing_status": "T",
            "hydrologic_huc_12": "171100020101",
            "hydrologic_hu_12_name": "Puget Sound",
            "hydrologic_hu_area_sqkm": 42.5,
            "link_feature_access": "AC",
        }
    }
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: SIMPLE_GEOMETRY)

    def query_features(_url, layer_id, _geometry, **_kwargs):
        features = [layer1] if layer_id == api.ESA_RANGES_FISH_LAYER_ID else []
        return ArcGISFeatureQueryResult(features=features, warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
    result = api.get_esa_species_ranges_in_roi(48.94, -122.93, 5.0)

    assert result["total"] == 1
    assert result["species"][0]["listed_entity"] == "Steelhead (Puget Sound DPS)"
    assert result["species"][0]["scientific_name"] == "Oncorhynchus mykiss"


def test_efh_uses_mapper_services_and_parses_each_shape(monkeypatch) -> None:
    api = _load_api("efh")
    calls: list[str] = []
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: SIMPLE_GEOMETRY)

    responses = {
        api.EFH_MAPPER_HAPC_SERVICE_URL: [{"attributes": {"HAPC_Siten": "Rocky Reefs", "FisheryM_5": "PFMC"}}],
        api.EFH_MAPPER_EFHA_SERVICE_URL: [
            {"attributes": {"SITENAME_L": "Estuary EFH", "TYPE": "EFHA", "FMC_REPORT": "PFMC"}}
        ],
        api.EFH_MAPPER_PACIFIC_SALMON_SERVICE_URL: [
            {
                "attributes": {
                    "HUC_8": "17100203",
                    "HUC_8_Name": "Nehalem",
                    "State": "OR",
                    "ChinookEFH": "Y",
                    "Coho_EFH": "Y",
                    "Pink_EFH": "N",
                    "All_EFH": "Y",
                }
            }
        ],
        api.EFH_MAPPER_EFH_SERVICE_URL: [
            {
                "attributes": {
                    "SITENAME_L": "Pacific Coast Groundfish",
                    "LIFESTAGE": "ALL",
                    "TYPE": "EFH",
                    "FMC": "PFMC",
                    "ZONE": "ALL",
                }
            }
        ],
    }

    def query_features(service_url, _layer_id, _geometry, **_kwargs):
        calls.append(service_url)
        return ArcGISFeatureQueryResult(features=responses[service_url], warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)

    assert api.get_hapc_in_roi(44.6, -124.2, 5.0)["hapc"][0]["species"] == "Rocky Reefs"
    assert api.get_efh_areas_in_roi(44.6, -124.2, 5.0)["efh_areas"][0]["species"] == "Estuary EFH"
    assert api.get_salmon_efh_in_roi(44.6, -124.2, 5.0)["watersheds"][0]["huc_8_name"] == "Nehalem"
    assert (
        api.get_hms_cps_groundfish_efh_in_roi(44.6, -124.2, 5.0)["efh_areas"][0]["species"]
        == "Pacific Coast Groundfish"
    )
    assert set(calls) == set(responses)


def test_noaa_dedup_preserves_units_without_fragment_overcount() -> None:
    api = _load_api("noaa")
    features = [
        {
            "attributes": {
                "comname": "Humpback whale",
                "listentity": "Humpback whale, Mexico DPS",
                "unit": "Unit A",
                "areasqkm": 1.25,
            }
        },
        {
            "attributes": {
                "comname": "Humpback whale",
                "listentity": "Humpback whale, Mexico DPS",
                "unit": "Unit B",
                "areasqkm": 2.75,
            }
        },
    ]

    deduplicated = api._deduplicate_fragments(features, 2, "polygon")

    assert len(deduplicated) == 1
    assert deduplicated[0]["units"] == ["Unit A", "Unit B"]
    assert deduplicated[0]["unit_count"] == 2
    assert deduplicated[0]["area_sqkm"] == 4.0


def test_nrhp_still_queries_polygon_then_point_and_prefers_polygon(monkeypatch) -> None:
    api = _load_api("nrhp")
    calls: list[int] = []
    assert "/cultural_resources/" in api.NRHP_SERVICE_URL
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: SIMPLE_GEOMETRY)

    def query_features(_url, layer_id, _geometry, **_kwargs):
        calls.append(layer_id)
        feature = {
            "attributes": {
                "NRIS_Refnum": "123",
                "RESNAME": "Shared Historic Property",
                "State": "WA",
            }
        }
        return ArcGISFeatureQueryResult(features=[feature], warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
    result = api.get_nrhp_properties_in_roi(46.64, -120.59, 5.0)

    assert calls == [1, 0]
    assert result["total"] == 1
    assert result["properties"][0]["geometry_type"] == api.NRHP_LAYERS[1]


def test_pcsrf_keeps_existing_non_project_dataset_semantics() -> None:
    api = _load_api("pcsrf")

    assert "All_Species_Ranges" in api.PCSRF_SPECIES_RANGES_URL
    assert "20210904" in api.PCSRF_CRITICAL_HABITAT_POLY_URL
    assert "Atlantic_salmon_EFH_HAPC_Buffer" in api.PCSRF_EFH_URL
    assert "PCSRF_Projects_Display" in api.PCSRF_PROJECTS_URL


def test_coverage_warning_is_post_query_and_uses_full_geometry() -> None:
    chicago_geometry = {"rings": [[[-88.0, 41.5], [-87.0, 41.5], [-87.0, 42.0], [-88.0, 42.0], [-88.0, 41.5]]]}
    result = {"total": 0, "species": []}

    annotated = add_empty_result_coverage_warning(
        result,
        chicago_geometry,
        bounds=NOAA_WEST_COAST_EXPECTED_BOUNDS,
        dataset_name="NOAA test dataset",
    )

    assert annotated["outside_expected_coverage"] is True
    assert "should not be interpreted" in annotated["coverage_warning"]
