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
        },
        "geometry": SIMPLE_GEOMETRY,
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
        },
        "geometry": SIMPLE_GEOMETRY,
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
    assert result["species"][0]["source_area_sqkm"] == 999.0
    assert result["species"][0]["area_sqkm"] > 0
    assert result["species"][0]["area_status"] == "ok"
    assert result["species"][0]["area_complete"] is False
    assert any("Both NOAA ESA range layers" in warning for warning in result["warnings"])


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
        },
        "geometry": SIMPLE_GEOMETRY,
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
                },
                "geometry": SIMPLE_GEOMETRY,
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


def test_noaa_polygon_area_is_clipped_and_source_area_is_retained() -> None:
    api = _load_api("noaa")
    feature = {
        "attributes": {
            "comname": "Test whale",
            "listentity": "Test whale DPS",
            "unit": "Unit A",
            "areasqkm": 99_999.0,
        },
        "geometry": SIMPLE_GEOMETRY,
    }

    one = api._deduplicate_fragments(
        [feature],
        2,
        "polygon",
        roi_geometry=SIMPLE_GEOMETRY,
    )[0]
    duplicate = api._deduplicate_fragments(
        [feature, feature],
        2,
        "polygon",
        roi_geometry=SIMPLE_GEOMETRY,
    )[0]

    assert one["area_status"] == "ok"
    assert one["area_sqkm"] > 0
    assert one["area_sqkm"] < one["source_area_sqkm"]
    assert one["source_area_sqkm"] == 99_999.0
    assert duplicate["area_sqkm"] == one["area_sqkm"]
    assert duplicate["source_area_sqkm"] == 199_998.0


def test_noaa_missing_geometry_does_not_masquerade_as_clipped_area() -> None:
    api = _load_api("noaa")
    habitat = api._deduplicate_fragments(
        [
            {
                "attributes": {
                    "comname": "Test whale",
                    "listentity": "Test whale DPS",
                    "areasqkm": 42.0,
                }
            }
        ],
        2,
        "polygon",
        roi_geometry=SIMPLE_GEOMETRY,
    )[0]

    assert habitat["area_sqkm"] is None
    assert habitat["source_area_sqkm"] == 42.0
    assert habitat["area_status"] == "no_geometry"
    assert habitat["area_complete"] is False
    assert any("No feature polygon geometries" in warning for warning in habitat["area_warnings"])


def test_noaa_truncated_geometry_marks_area_incomplete() -> None:
    api = _load_api("noaa")
    feature = {
        "attributes": {"listentity": "Test whale DPS", "areasqkm": 42.0},
        "geometry": SIMPLE_GEOMETRY,
    }

    habitat = api._deduplicate_fragments(
        [feature],
        2,
        "polygon",
        roi_geometry=SIMPLE_GEOMETRY,
        geometry_complete=False,
    )[0]

    assert habitat["area_status"] == "ok"
    assert habitat["area_complete"] is False
    assert "may be understated" in habitat["area_warnings"][-1]


def test_noaa_skipped_fragment_marks_area_incomplete() -> None:
    api = _load_api("noaa")
    valid = {
        "attributes": {"listentity": "Test whale DPS", "areasqkm": 42.0},
        "geometry": SIMPLE_GEOMETRY,
    }
    invalid = {
        "attributes": {"listentity": "Test whale DPS", "areasqkm": 2.0},
        "geometry": {"paths": [[[0.0, 0.0], [1.0, 1.0]]]},
    }

    habitat = api._deduplicate_fragments(
        [valid, invalid],
        2,
        "polygon",
        roi_geometry=SIMPLE_GEOMETRY,
    )[0]

    assert habitat["area_status"] == "ok"
    assert habitat["area_complete"] is False
    assert any("Line paths" in warning for warning in habitat["area_warnings"])


def test_noaa_queries_geometry_only_for_polygon_layer(monkeypatch) -> None:
    api = _load_api("noaa")
    calls: dict[int, dict] = {}

    def query_features(_url, layer_id, _geometry, **kwargs):
        calls[layer_id] = kwargs
        features = []
        if layer_id == 2:
            features = [
                {
                    "attributes": {
                        "comname": "Test whale",
                        "listentity": "Test whale DPS",
                        "areasqkm": 99_999.0,
                    },
                    "geometry": SIMPLE_GEOMETRY,
                }
            ]
        return ArcGISFeatureQueryResult(features=features, warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)

    habitats, warnings = api._query_noaa_ch_layers(SIMPLE_GEOMETRY)

    assert warnings == []
    assert calls[1]["return_geometry"] is False
    assert calls[1]["out_sr"] is None
    assert calls[2]["return_geometry"] is True
    assert calls[2]["out_sr"] == 4326
    assert calls[2]["simplify_geometry"] is False
    assert habitats[0]["area_status"] == "ok"
    assert habitats[0]["area_complete"] is True


def test_noaa_propagates_missing_geometry_and_truncation_warnings(monkeypatch) -> None:
    api = _load_api("noaa")

    def query_features(_url, layer_id, _geometry, **_kwargs):
        if layer_id == 2:
            return ArcGISFeatureQueryResult(
                features=[
                    {
                        "attributes": {
                            "listentity": "Test whale DPS",
                            "areasqkm": 42.0,
                        }
                    }
                ],
                warnings=["NOAA polygon layer reached the feature safety cap."],
                truncated=True,
            )
        return ArcGISFeatureQueryResult(features=[], warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)

    habitats, warnings = api._query_noaa_ch_layers(SIMPLE_GEOMETRY)

    assert habitats[0]["area_status"] == "no_geometry"
    assert habitats[0]["area_complete"] is False
    assert any("feature safety cap" in warning for warning in warnings)
    assert any("No feature polygon geometries" in warning for warning in warnings)
    assert any("may be understated" in warning for warning in warnings)


def test_noaa_summary_labels_clipped_area_explicitly() -> None:
    api = _load_api("noaa")
    summary = api.format_noaa_critical_habitat_summary(
        {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 5.0,
            "total": 1,
            "species_count": 1,
            "named_unit_count": 1,
            "habitats": [
                {
                    "listed_entity": "Test whale DPS",
                    "scientific_name": "Testus whaleus",
                    "listing_status": "Endangered",
                    "taxon": "Marine mammal",
                    "units": ["Unit A"],
                    "area_sqkm": 1.25,
                    "source_area_sqkm": 42.0,
                    "area_status": "ok",
                    "length_km": None,
                    "federal_register": "",
                }
            ],
            "warnings": [],
        }
    )

    assert "Area within ROI: 1.25 sq km" in summary
    assert "Source feature-area total (not clipped to ROI): 42.0 sq km" in summary
    assert "Combined intersecting extent" not in summary


def test_noaa_summary_exposes_unavailable_area_and_source_line_length() -> None:
    api = _load_api("noaa")
    summary = api.format_noaa_critical_habitat_summary(
        {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 5.0,
            "total": 2,
            "species_count": 1,
            "named_unit_count": 0,
            "habitats": [
                {
                    "listed_entity": "Test salmon DPS",
                    "scientific_name": "Testus salmonus",
                    "listing_status": "Threatened",
                    "taxon": "Fish",
                    "units": [],
                    "area_sqkm": None,
                    "area_status": "no_geometry",
                    "length_km": None,
                    "federal_register": "",
                },
                {
                    "listed_entity": "Test salmon DPS",
                    "scientific_name": "Testus salmonus",
                    "listing_status": "Threatened",
                    "taxon": "Fish",
                    "units": [],
                    "area_sqkm": None,
                    "length_km": 12.5,
                    "federal_register": "",
                },
            ],
            "warnings": [],
        }
    )

    assert "Area within ROI: unavailable (no_geometry)" in summary
    assert "Intersecting line-feature length (source attribute): 12.5 km" in summary


def test_noaa_summary_keeps_legacy_area_visible() -> None:
    api = _load_api("noaa")
    summary = api.format_noaa_critical_habitat_summary(
        {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 5.0,
            "total": 1,
            "species_count": 1,
            "named_unit_count": 0,
            "habitats": [
                {
                    "listed_entity": "Legacy whale DPS",
                    "scientific_name": "Testus whaleus",
                    "listing_status": "Endangered",
                    "taxon": "Marine mammal",
                    "units": [],
                    "area_sqkm": 42.0,
                    "length_km": None,
                    "federal_register": "",
                }
            ],
            "warnings": [],
        }
    )

    assert "Reported polygon area (source attribute): 42.0 sq km" in summary


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
