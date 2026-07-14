"""
Unit tests for the BLM API layer (``blm/src/apis/blm_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS query layer
mocked, so no network calls are made. They follow the same dynamic per-server
import pattern used by the USACE test suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-112.0, 38.0], [-111.0, 38.0], [-111.0, 39.0], [-112.0, 39.0], [-112.0, 38.0]]],
    "spatialReference": {"wkid": 4326},
}
# Shape__Area value (square meters) that converts to exactly 1.0 sq mi.
SQ_METERS_ONE_SQ_MILE = 2589988.11


def _load_blm_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "blm"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_blm_unit_api",
            server_dir / "src" / "apis" / "blm_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_blm_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, feature_map, warnings=None):
    """Return features keyed by service_name substring."""

    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


# ---------------------------------------------------------------------------
# Land use plans
# ---------------------------------------------------------------------------


class TestLandUsePlans:
    def test_parses_plan_fields(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "land use plans": [
                    {
                        "attributes": {
                            "LUPName": "Grand Staircase RMP",
                            "Status": "Approved",
                            "RODdate": "2020-02-06",
                            "RODyear": 2020,
                            "AdminSt": "UT",
                            "NEPAnum": "DOI-BLM-UT-1234",
                            "ePLink": "https://eplanning.blm.gov/xyz",
                            "Shape__Area": SQ_METERS_ONE_SQ_MILE,
                        }
                    }
                ]
            },
        )
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5, 25.0)
        assert result["total"] == 1
        plan = result["land_use_plans"][0]
        assert plan["plan_name"] == "Grand Staircase RMP"
        assert plan["status"] == "Approved"
        assert plan["rod_year"] == 2020
        assert plan["admin_state"] == "UT"
        assert plan["nepa_number"] == "DOI-BLM-UT-1234"
        assert plan["plan_link"].startswith("https://eplanning")
        assert plan["area_sq_mi"] == 1.0
        assert result["center"] == {"latitude": 38.5, "longitude": -111.5}

    def test_unknown_plan_when_fields_missing(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"land use plans": [{"attributes": {}}]})
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        assert result["land_use_plans"][0]["plan_name"] == "Unknown"
        assert result["land_use_plans"][0]["area_sq_mi"] is None

    def test_plans_sorted_by_name(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "land use plans": [
                    {"attributes": {"LUPName": "Zed RMP"}},
                    {"attributes": {"LUPName": "Alpha RMP"}},
                ]
            },
        )
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        names = [p["plan_name"] for p in result["land_use_plans"]]
        assert names == ["Alpha RMP", "Zed RMP"]

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        assert result["total"] == 0
        assert result["land_use_plans"] == []


# ---------------------------------------------------------------------------
# Wilderness areas
# ---------------------------------------------------------------------------


class TestWildernessAreas:
    def test_parses_wilderness_fields_and_date(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        # 946684800000 ms = 2000-01-01 (UTC); local conversion handled by api.
        _patch_query(
            api,
            monkeypatch,
            {
                "wilderness": [
                    {
                        "attributes": {
                            "NLCS_NAME": "Paria Canyon Wilderness",
                            "NLCS_ID": "NLCS-42",
                            "ADMIN_ST": "AZ",
                            "DESIG_DATE": 946684800000,
                            "CASEFILE_NO": "CF-99",
                            "Shape__Area": SQ_METERS_ONE_SQ_MILE * 2,
                        }
                    }
                ]
            },
        )
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        assert result["total"] == 1
        area = result["wilderness_areas"][0]
        assert area["name"] == "Paria Canyon Wilderness"
        assert area["nlcs_id"] == "NLCS-42"
        assert area["admin_state"] == "AZ"
        assert area["casefile_number"] == "CF-99"
        assert area["area_sq_mi"] == 2.0
        # Designation date should be an ISO-style string parsed from epoch ms.
        assert area["designation_date"] is not None
        assert area["designation_date"].startswith("2000") or area["designation_date"].startswith("1999")

    def test_missing_designation_date_is_none(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"wilderness": [{"attributes": {"NLCS_NAME": "X Wilderness"}}]})
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        assert result["wilderness_areas"][0]["designation_date"] is None

    def test_unknown_wilderness_when_fields_missing(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"wilderness": [{"attributes": {}}]})
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        assert result["wilderness_areas"][0]["name"] == "Unknown"


# ---------------------------------------------------------------------------
# National monuments / NCAs
# ---------------------------------------------------------------------------


class TestNationalMonuments:
    def test_parses_monument_fields(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "national monuments": [
                    {
                        "attributes": {
                            "NCA_NAME": "Grand Staircase-Escalante NM",
                            "NLCS_ID": "NLCS-1",
                            "STATE_ADMN": "UT",
                            "STATE_GEOG": "UT",
                            "sma_code": "NM",
                            "Shape__Area": SQ_METERS_ONE_SQ_MILE,
                        }
                    }
                ]
            },
        )
        result = api.get_blm_national_monuments_in_roi(38.5, -111.5)
        assert result["total"] == 1
        mon = result["national_monuments"][0]
        assert mon["name"] == "Grand Staircase-Escalante NM"
        assert mon["nlcs_id"] == "NLCS-1"
        assert mon["admin_state"] == "UT"
        assert mon["geographic_state"] == "UT"
        assert mon["sma_code"] == "NM"
        assert mon["area_sq_mi"] == 1.0

    def test_unknown_monument_when_fields_missing(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"national monuments": [{"attributes": {}}]})
        result = api.get_blm_national_monuments_in_roi(38.5, -111.5)
        assert result["national_monuments"][0]["name"] == "Unknown"

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_blm_national_monuments_in_roi(38.5, -111.5)
        assert result["total"] == 0
        assert result["national_monuments"] == []


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_land_use_summary_renders_markdown(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 1,
            "land_use_plans": [
                {
                    "plan_name": "Grand Staircase RMP",
                    "status": "Approved",
                    "rod_date": "2020-02-06",
                    "rod_year": 2020,
                    "admin_state": "UT",
                    "nepa_number": "DOI-BLM-UT-1234",
                    "plan_link": "https://eplanning.blm.gov/xyz",
                    "area_sq_mi": 1.0,
                }
            ],
            "warnings": [],
        }
        out = api.format_blm_land_use_plans_summary(data)
        assert "BLM Land Use Plans within ROI" in out
        assert "Grand Staircase RMP" in out
        assert "Total Plans: 1" in out
        assert "43 CFR 1610.5" in out
        assert "ePlanning: https://eplanning.blm.gov/xyz" in out

    def test_land_use_summary_handles_empty(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 0,
            "land_use_plans": [],
            "warnings": [],
        }
        out = api.format_blm_land_use_plans_summary(data)
        assert "No BLM land use plans found in the ROI." in out

    def test_wilderness_summary_renders_markdown(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 1,
            "wilderness_areas": [
                {
                    "name": "Paria Canyon Wilderness",
                    "nlcs_id": "NLCS-42",
                    "admin_state": "AZ",
                    "designation_date": "2000-01-01",
                    "casefile_number": "CF-99",
                    "area_sq_mi": 2.0,
                }
            ],
            "warnings": [],
        }
        out = api.format_blm_wilderness_summary(data)
        assert "BLM Wilderness Areas within ROI" in out
        assert "Paria Canyon Wilderness" in out
        assert "Total Wilderness Areas: 1" in out
        assert "Wilderness Act of 1964" in out
        assert "NLCS ID: NLCS-42" in out

    def test_wilderness_summary_handles_empty(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 0,
            "wilderness_areas": [],
            "warnings": [],
        }
        out = api.format_blm_wilderness_summary(data)
        assert "No BLM wilderness areas found in the ROI." in out

    def test_monuments_summary_renders_markdown(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 1,
            "national_monuments": [
                {
                    "name": "Grand Staircase-Escalante NM",
                    "nlcs_id": "NLCS-1",
                    "admin_state": "UT",
                    "geographic_state": "UT",
                    "sma_code": "NM",
                    "area_sq_mi": 1.0,
                }
            ],
            "warnings": [],
        }
        out = api.format_blm_monuments_summary(data)
        assert "BLM National Monuments and NCAs within ROI" in out
        assert "Grand Staircase-Escalante NM" in out
        assert "Total Designations: 1" in out
        assert "Extraordinary Circumstances" in out

    def test_monuments_summary_handles_empty(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 0,
            "national_monuments": [],
            "warnings": [],
        }
        out = api.format_blm_monuments_summary(data)
        assert "No BLM National Monuments or NCAs found in the ROI." in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_blm_api()
        data = {
            "center": {"latitude": 38.5, "longitude": -111.5},
            "buffer_miles": 25.0,
            "total": 0,
            "land_use_plans": [],
            "warnings": ["upstream degraded"],
        }
        out = api.format_blm_land_use_plans_summary(data)
        assert "Warning: upstream degraded" in out
