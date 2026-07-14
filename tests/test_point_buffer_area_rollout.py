from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult


ROOT = Path(__file__).resolve().parents[1]
ROI = {
    "rings": [
        [
            [-121.0, 46.0],
            [-120.0, 46.0],
            [-120.0, 47.0],
            [-121.0, 47.0],
            [-121.0, 46.0],
        ]
    ],
    "spatialReference": {"wkid": 4326},
}


def _load_api(server_name: str):
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)

    server_dir = ROOT / server_name
    sys.path.insert(0, str(server_dir))
    try:
        module_name = f"_point_buffer_area_{server_name}"
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


def _esa_layer2_feature(*, geometry=ROI, area: float = 999.0) -> dict:
    feature = {
        "attributes": {
            "listentity": "STUCR",
            "liststatus": "T",
            "sciename": "3",
            "comname": "ST",
            "taxon": "3",
            "leadoffice": "WCR",
            "areasqkm": area,
            "huc12": "170200160601",
            "huc12_name": "Parsons Canyon-Columbia River",
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _pcsrf_ch_feature(*, geometry=ROI, area: float = 999.0) -> dict:
    feature = {
        "attributes": {
            "COMNAME": "Test salmon",
            "SCIENAME": "Testus salmonus",
            "LISTENTITY": "Test salmon DPS",
            "LISTSTATUS": "Threatened",
            "UNIT": "Unit A",
            "AREASqKm": area,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _efh_feature(*, geometry=ROI, acres: float = 999.0) -> dict:
    feature = {
        "attributes": {
            "SITENAME_L": "Pacific Coast Groundfish",
            "LIFESTAGE": "ALL",
            "TYPE": "EFH",
            "FMC": "PFMC",
            "ZONE": "ALL",
            "ACRES": acres,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def test_esa_duplicate_fragments_are_unioned_and_source_area_is_retained() -> None:
    api = _load_api("esa_ranges")
    feature = _esa_layer2_feature()

    one = api._deduplicate_ranges([feature], roi_geometry=ROI)[0]
    duplicate = api._deduplicate_ranges([feature, feature], roi_geometry=ROI)[0]

    assert one["area_status"] == "ok"
    assert one["area_complete"] is True
    assert one["area_sqkm"] > 0
    assert duplicate["area_sqkm"] == one["area_sqkm"]
    assert duplicate["source_area_sqkm"] == 1_998.0


def test_esa_missing_geometry_is_not_reported_as_zero_area() -> None:
    api = _load_api("esa_ranges")

    record = api._deduplicate_ranges(
        [_esa_layer2_feature(geometry=None)],
        roi_geometry=ROI,
    )[0]

    assert record["area_sqkm"] is None
    assert record["source_area_sqkm"] == 999.0
    assert record["area_status"] == "no_geometry"
    assert record["area_complete"] is False


def test_esa_queries_geometry_for_both_layers_and_marks_truncation(monkeypatch) -> None:
    api = _load_api("esa_ranges")
    calls: dict[int, dict] = {}
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: ROI)

    def query_features(_url, layer_id, _geometry, **kwargs):
        calls[layer_id] = kwargs
        features = [_esa_layer2_feature()] if layer_id == api.ESA_RANGES_LAYER_ID else []
        return ArcGISFeatureQueryResult(
            features=features,
            warnings=["partial"] if features else [],
            truncated=bool(features),
        )

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)

    result = api.get_esa_species_ranges_in_roi(46.5, -120.5, 5.0)

    assert all(call["return_geometry"] is True for call in calls.values())
    assert all(call["out_sr"] == 4326 for call in calls.values())
    assert all(call["simplify_geometry"] is False for call in calls.values())
    assert result["species"][0]["area_complete"] is False
    assert any("may be understated" in warning for warning in result["warnings"])
    assert "Partial area within ROI" in api.format_esa_species_ranges_summary(result)


def test_esa_layer1_repeated_huc_area_is_not_multiplied() -> None:
    api = _load_api("esa_ranges")
    base = {
        "dps": "Steelhead (Puget Sound DPS)",
        "dps_id": "STPUG",
        "species": "ST",
        "listing_status": "T",
        "hydrologic_huc_12": "171100020101",
        "hydrologic_hu_12_name": "Puget Sound",
        "hydrologic_hu_area_sqkm": 42.5,
    }

    record = api._normalize_layer1(
        [
            {"attributes": {**base, "population": "A"}, "geometry": ROI},
            {"attributes": {**base, "population": "B"}, "geometry": ROI},
        ]
    )[0]

    assert record["source_area_sqkm"] == 42.5


def test_esa_formatter_distinguishes_roi_and_source_area() -> None:
    api = _load_api("esa_ranges")
    summary = api.format_esa_species_ranges_summary(
        {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 5.0,
            "total": 1,
            "species_count": 1,
            "watershed_count": 1,
            "warnings": [],
            "species": [
                {
                    "listed_entity": "Test salmon DPS",
                    "scientific_name": "Testus salmonus",
                    "listing_status": "Threatened",
                    "taxon": "fish",
                    "huc12": "123",
                    "huc12_name": "Test watershed",
                    "feature_access": "",
                    "area_sqkm": 1.25,
                    "source_area_sqkm": 99.0,
                    "area_status": "ok",
                }
            ],
        }
    )

    assert "Area within ROI: 1.2 sq km" in summary
    assert "Source watershed-area total (not clipped to ROI): 99.0 sq km" in summary


def test_pcsrf_critical_habitat_duplicate_fragments_are_unioned() -> None:
    api = _load_api("pcsrf")
    feature = _pcsrf_ch_feature()

    one = api._deduplicate_ch_fragments([feature], "polygon", roi_geometry=ROI)[0]
    duplicate = api._deduplicate_ch_fragments([feature, feature], "polygon", roi_geometry=ROI)[0]

    assert one["area_status"] == "ok"
    assert duplicate["area_sqkm"] == one["area_sqkm"]
    assert duplicate["source_area_sqkm"] == 1_998.0


def test_pcsrf_critical_habitat_lines_remain_length_only() -> None:
    api = _load_api("pcsrf")
    record = api._deduplicate_ch_fragments(
        [{"attributes": {"LISTENTITY": "Test salmon DPS", "UNIT": "River", "Shape__Length": 1.0}}],
        "line",
        roi_geometry=ROI,
    )[0]

    assert record["area_sqkm"] is None
    assert record["length_km"] == 111.0
    assert "area_status" not in record


def test_pcsrf_efh_area_is_clipped_and_missing_geometry_is_explicit() -> None:
    api = _load_api("pcsrf")
    feature = {
        "attributes": {
            "GNIS_Name": "Atlantic salmon EFH",
            "TYPE": "EFH",
            "REGION": "GAR",
            "Shape__Area": 12345.0,
        },
        "geometry": ROI,
    }

    clipped = api._parse_efh([feature, feature], roi_geometry=ROI)[0]
    missing = api._parse_efh([{**feature, "geometry": None}], roi_geometry=ROI)[0]

    assert clipped["area_acres"] > 0
    assert clipped["area_status"] == "ok"
    assert clipped["area_sq_units"] == 24_690.0
    assert missing["area_acres"] is None
    assert missing["area_status"] == "no_geometry"


def test_pcsrf_efh_parser_preserves_legacy_cardinality_without_roi() -> None:
    api = _load_api("pcsrf")
    features = [
        {
            "attributes": {
                "GNIS_Name": "Atlantic salmon EFH",
                "TYPE": "EFH",
                "REGION": "GAR",
                "LINK": f"https://example.test/{index}",
                "BUFF_DIST": index,
                "Shape__Area": float(index),
            }
        }
        for index in (1, 2)
    ]

    records = api._parse_efh(features)

    assert len(records) == 2
    assert {record["link"] for record in records} == {
        "https://example.test/1",
        "https://example.test/2",
    }
    assert all("area_status" not in record for record in records)


def test_pcsrf_geometry_queries_are_opt_in_and_truncation_is_propagated(monkeypatch) -> None:
    api = _load_api("pcsrf")
    calls: dict[str, dict] = {}
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: ROI)

    def query_features(service_url, _layer_id, _geometry, **kwargs):
        calls[service_url] = kwargs
        if service_url == api.PCSRF_CRITICAL_HABITAT_POLY_URL:
            return ArcGISFeatureQueryResult(features=[_pcsrf_ch_feature()], warnings=[], truncated=True)
        return ArcGISFeatureQueryResult(features=[], warnings=[])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
    result = api.get_critical_habitat_in_roi(46.5, -120.5, 5.0)

    assert calls[api.PCSRF_CRITICAL_HABITAT_POLY_URL]["return_geometry"] is True
    assert calls[api.PCSRF_CRITICAL_HABITAT_POLY_URL]["out_sr"] == 4326
    assert calls[api.PCSRF_CRITICAL_HABITAT_POLY_URL]["simplify_geometry"] is False
    assert calls[api.PCSRF_CRITICAL_HABITAT_LINE_URL]["return_geometry"] is False
    assert result["habitats"][0]["area_complete"] is False
    assert any("may be understated" in warning for warning in result["warnings"])


def test_pcsrf_formatters_label_roi_area_and_source_line_length() -> None:
    api = _load_api("pcsrf")
    summary = api.format_critical_habitat_summary(
        {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 5.0,
            "total": 2,
            "species_count": 1,
            "warnings": [],
            "habitats": [
                {
                    "listed_entity": "Test salmon DPS",
                    "scientific_name": "Testus salmonus",
                    "listing_status": "Threatened",
                    "taxon": "fish",
                    "unit": "Polygon",
                    "habitat_type": "polygon",
                    "area_sqkm": 1.0,
                    "source_area_sqkm": 99.0,
                    "area_status": "ok",
                    "length_km": None,
                },
                {
                    "listed_entity": "Test salmon DPS",
                    "scientific_name": "Testus salmonus",
                    "listing_status": "Threatened",
                    "taxon": "fish",
                    "unit": "River",
                    "habitat_type": "line",
                    "area_sqkm": None,
                    "length_km": 12.5,
                },
            ],
        }
    )

    assert "1.0 sq km within ROI" in summary
    assert "Source feature-area total (not clipped to ROI): 99.0 sq km" in summary
    assert "12.5 km (legacy estimate; not ROI-clipped)" in summary


def test_pcsrf_formatters_label_incomplete_area_as_partial() -> None:
    api = _load_api("pcsrf")
    summary = api.format_efh_summary(
        {
            "center": {"latitude": 44.8, "longitude": -68.8},
            "buffer_miles": 5.0,
            "total": 1,
            "warnings": ["partial"],
            "efh_areas": [
                {
                    "gnis_name": "Atlantic salmon EFH",
                    "type": "EFH",
                    "region": "GAR",
                    "area_acres": 12.5,
                    "area_status": "ok",
                    "area_complete": False,
                }
            ],
        }
    )

    assert "Partial area within ROI: 12.50 acres" in summary


def test_pcsrf_critical_habitat_formatter_treats_legacy_area_as_source() -> None:
    api = _load_api("pcsrf")
    summary = api.format_critical_habitat_summary(
        {
            "center": {"latitude": 44.8, "longitude": -68.8},
            "buffer_miles": 5.0,
            "total": 1,
            "species_count": 1,
            "warnings": [],
            "habitats": [
                {
                    "listed_entity": "Legacy salmon DPS",
                    "scientific_name": "Testus salmonus",
                    "listing_status": "Threatened",
                    "taxon": "fish",
                    "unit": "Unit A",
                    "habitat_type": "polygon",
                    "area_sqkm": 42.0,
                    "length_km": None,
                }
            ],
        }
    )

    assert "42.0 sq km source area" in summary
    assert "42.0 sq km within ROI" not in summary


def test_efh_duplicate_fragments_are_unioned_and_source_acres_are_retained() -> None:
    api = _load_api("efh")
    feature = _efh_feature()

    one = api._deduplicate_efh([feature], roi_geometry=ROI)[0]
    duplicate = api._deduplicate_efh([feature, feature], roi_geometry=ROI)[0]

    assert one["area_status"] == "ok"
    assert one["area_complete"] is True
    assert duplicate["acres"] == one["acres"]
    assert duplicate["source_acres"] == 1_998.0


def test_efh_missing_geometry_is_incomplete_and_not_zero() -> None:
    api = _load_api("efh")
    record = api._deduplicate_efh(
        [_efh_feature(geometry=None)],
        roi_geometry=ROI,
    )[0]

    assert record["acres"] is None
    assert record["source_acres"] == 999.0
    assert record["area_status"] == "no_geometry"
    assert record["area_complete"] is False


def test_efh_only_species_area_query_requests_geometry(monkeypatch) -> None:
    api = _load_api("efh")
    calls: dict[str, dict] = {}
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_args: ROI)

    def query_features(service_url, _layer_id, _geometry, **kwargs):
        calls[service_url] = kwargs
        features = [_efh_feature()] if service_url == api.EFH_MAPPER_EFH_SERVICE_URL else []
        return ArcGISFeatureQueryResult(
            features=features,
            warnings=[],
            truncated=service_url == api.EFH_MAPPER_EFH_SERVICE_URL,
        )

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)

    hms = api.get_hms_cps_groundfish_efh_in_roi(46.5, -120.5, 5.0)
    hapc = api.get_hapc_in_roi(46.5, -120.5, 5.0)

    assert calls[api.EFH_MAPPER_EFH_SERVICE_URL]["return_geometry"] is True
    assert calls[api.EFH_MAPPER_EFH_SERVICE_URL]["out_sr"] == 4326
    assert calls[api.EFH_MAPPER_EFH_SERVICE_URL]["simplify_geometry"] is False
    assert calls[api.EFH_MAPPER_HAPC_SERVICE_URL]["return_geometry"] is False
    assert hms["efh_areas"][0]["area_complete"] is False
    assert any("may be understated" in warning for warning in hms["warnings"])
    assert "Partial area within ROI" in api.format_hms_cps_groundfish_summary(hms)
    assert hapc["hapc"] == []


@pytest.mark.parametrize("status", ["ok", "no_geometry"])
def test_efh_formatter_labels_area_provenance(status: str) -> None:
    api = _load_api("efh")
    entry = {
        "species": "Pacific Coast Groundfish",
        "fmc": "PFMC",
        "lifestage": "ALL",
        "zone": "ALL",
        "acres": 12.5 if status == "ok" else None,
        "source_acres": 999.0,
        "area_status": status,
    }
    lines: list[str] = []

    api._append_efh_entries(lines, [entry])
    rendered = "\n".join(lines)

    if status == "ok":
        assert "Area within ROI: 12.50 acres" in rendered
        assert "Source feature-area total (not clipped to ROI): 999.00 acres" in rendered
    else:
        assert "Area within ROI: unavailable (no_geometry)" in rendered
