"""
Unit tests for the FEMA NFHL API layer (``fema_nfhl/src/apis/fema_nfhl_api.py``).

These exercise the pure parsing/summary/formatting logic with the network layer
(``requests.get``) mocked, so no network calls are made. They follow the same
dynamic per-server import pattern used by ``test_fema_nfhl_api.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "fema_nfhl"

# NFHL MapServer layer IDs (mirrors LAYERS in the api module).
FLOOD_ZONES_LAYER = 28
LEVEES_LAYER = 23
WATER_AREAS_LAYER = 32


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def _load_fema_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_fema_unit_"):
            sys.modules.pop(module_name, None)
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    module_path = SERVER_DIR / "src" / "apis" / "fema_nfhl_api.py"
    spec = importlib.util.spec_from_file_location("_fema_unit_api", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fema_unit_api"] = module
    spec.loader.exec_module(module)
    return module


def _features(attr_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"attributes": attrs} for attrs in attr_list]


def _install_requests_mock(fema_api, monkeypatch, layer_features, exceeded: bool = False):
    """Route a mocked ``requests.get`` by NFHL layer id embedded in the URL.

    ``layer_features`` maps layer id (int) -> list of attribute dicts.
    """

    def fake_get(url: str, *, params: dict[str, Any], timeout: int):
        layer_id = int(url.rstrip("/").split("/")[-2])
        attrs = layer_features.get(layer_id, [])
        return _FakeResponse({"exceededTransferLimit": exceeded, "features": _features(attrs)})

    monkeypatch.setattr(fema_api.requests, "get", fake_get)


# ---------------------------------------------------------------------------
# Flood zones
# ---------------------------------------------------------------------------


class TestFloodZones:
    def test_parses_zones_and_summary(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(
            fema_api,
            monkeypatch,
            {
                FLOOD_ZONES_LAYER: [
                    {"FLD_ZONE": "AE", "SFHA_TF": "T"},
                    {"FLD_ZONE": "AE", "SFHA_TF": "T"},
                    {"FLD_ZONE": "X", "SFHA_TF": "F"},
                ]
            },
        )
        result = fema_api.get_flood_zones(29.95, -90.07, 25.0)
        assert result["total_zones"] == 3
        assert result["center"] == {"latitude": 29.95, "longitude": -90.07}
        assert result["radius_miles"] == 25.0
        summary = result["summary"]
        assert summary["zone_counts"] == {"AE": 2, "X": 1}
        assert summary["sfha_count"] == 2
        assert summary["sfha_percentage"] == 66.7

    def test_empty_zones_yields_zero(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(fema_api, monkeypatch, {FLOOD_ZONES_LAYER: []})
        result = fema_api.get_flood_zones(29.95, -90.07)
        assert result["total_zones"] == 0
        assert result["zones"] == []
        assert result["summary"]["sfha_percentage"] == 0

    def test_missing_zone_field_labeled_unknown(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(fema_api, monkeypatch, {FLOOD_ZONES_LAYER: [{"SFHA_TF": "F"}]})
        result = fema_api.get_flood_zones(29.95, -90.07)
        assert result["summary"]["zone_counts"] == {"Unknown": 1}


# ---------------------------------------------------------------------------
# Levees
# ---------------------------------------------------------------------------


class TestLevees:
    def test_parses_levees(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(
            fema_api,
            monkeypatch,
            {LEVEES_LAYER: [{"OBJECTID": 1}, {"OBJECTID": 2}]},
        )
        result = fema_api.get_levees(29.95, -90.07)
        assert result["total_levees"] == 2
        assert len(result["levees"]) == 2

    def test_empty_levees(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(fema_api, monkeypatch, {LEVEES_LAYER: []})
        result = fema_api.get_levees(29.95, -90.07)
        assert result["total_levees"] == 0
        assert result["levees"] == []


# ---------------------------------------------------------------------------
# Water areas
# ---------------------------------------------------------------------------


class TestWaterAreas:
    def test_parses_water_areas(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(
            fema_api,
            monkeypatch,
            {WATER_AREAS_LAYER: [{"OBJECTID": 10}]},
        )
        result = fema_api.get_water_areas(29.95, -90.07)
        assert result["total_water_areas"] == 1
        assert result["water_areas"][0]["OBJECTID"] == 10


# ---------------------------------------------------------------------------
# Flood-risk screening (combines all three layers)
# ---------------------------------------------------------------------------


class TestAnalyzeFloodRisk:
    def test_high_hazard_when_majority_sfha(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(
            fema_api,
            monkeypatch,
            {
                FLOOD_ZONES_LAYER: [
                    {"FLD_ZONE": "AE", "SFHA_TF": "T"},
                    {"FLD_ZONE": "AE", "SFHA_TF": "T"},
                    {"FLD_ZONE": "X", "SFHA_TF": "F"},
                ],
                LEVEES_LAYER: [{"OBJECTID": 1}],
                WATER_AREAS_LAYER: [{"OBJECTID": 2}],
            },
        )
        result = fema_api.analyze_flood_risk(29.95, -90.07)
        screening = result["hazard_screening"]
        assert screening["hazard_level"] == "HIGH"
        assert screening["sfha_percentage"] == 66.7
        assert screening["has_levee_protection"] is True
        assert result["flood_zones"]["total_zones"] == 3
        assert result["levees"]["total_levees"] == 1
        assert result["water_areas"]["total_water_areas"] == 1

    def test_minimal_hazard_when_no_sfha(self, monkeypatch):
        fema_api = _load_fema_api()
        _install_requests_mock(
            fema_api,
            monkeypatch,
            {
                FLOOD_ZONES_LAYER: [{"FLD_ZONE": "X", "SFHA_TF": "F"}],
                LEVEES_LAYER: [],
                WATER_AREAS_LAYER: [],
            },
        )
        result = fema_api.analyze_flood_risk(29.95, -90.07)
        screening = result["hazard_screening"]
        assert screening["hazard_level"] == "MINIMAL"
        assert screening["has_levee_protection"] is False


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_flood_zones_summary_renders_markdown(self):
        fema_api = _load_fema_api()
        data = {
            "center": {"latitude": 29.95, "longitude": -90.07},
            "radius_miles": 25.0,
            "total_zones": 3,
            "zones": [],
            "summary": {"zone_counts": {"AE": 2, "X": 1}, "sfha_count": 2, "sfha_percentage": 66.7},
            "warnings": [],
        }
        out = fema_api.format_flood_zones_summary(data)
        assert "FEMA Flood Zones Analysis" in out
        assert "Total: 3" in out
        assert "SFHA Zones: 2 (66.7%)" in out
        assert "AE: 2 zones" in out

    def test_levees_summary_renders_markdown(self):
        fema_api = _load_fema_api()
        data = {
            "center": {"latitude": 29.95, "longitude": -90.07},
            "radius_miles": 25.0,
            "total_levees": 1,
            "levees": [],
            "warnings": [],
        }
        out = fema_api.format_levees_summary(data)
        assert "FEMA Levees" in out
        assert "Total: 1" in out

    def test_water_areas_summary_renders_markdown(self):
        fema_api = _load_fema_api()
        data = {
            "center": {"latitude": 29.95, "longitude": -90.07},
            "radius_miles": 25.0,
            "total_water_areas": 0,
            "water_areas": [],
            "warnings": [],
        }
        out = fema_api.format_water_areas_summary(data)
        assert "FEMA Water Areas" in out
        assert "Total: 0" in out

    def test_summary_surfaces_warnings(self):
        fema_api = _load_fema_api()
        data = {
            "center": {"latitude": 29.95, "longitude": -90.07},
            "radius_miles": 25.0,
            "total_levees": 0,
            "levees": [],
            "warnings": ["upstream degraded"],
        }
        out = fema_api.format_levees_summary(data)
        assert "Warning: upstream degraded" in out

    def test_flood_risk_summary_has_screening_sections(self):
        fema_api = _load_fema_api()
        data = {
            "center": {"latitude": 29.95, "longitude": -90.07},
            "radius_miles": 25.0,
            "flood_zones": {
                "total_zones": 3,
                "warnings": [],
                "summary": {"zone_counts": {"AE": 2, "X": 1}, "sfha_count": 2, "sfha_percentage": 66.7},
            },
            "levees": {"total_levees": 1, "warnings": []},
            "water_areas": {"total_water_areas": 0, "warnings": []},
            "hazard_screening": {
                "hazard_level": "HIGH",
                "hazard_description": "Significant portion of returned NFHL records are within SFHAs",
                "sfha_percentage": 66.7,
                "has_levee_protection": True,
            },
        }
        out = fema_api.format_flood_risk_summary(data)
        assert "FEMA NFHL Flood-Hazard Screening" in out
        assert "Hazard Level: HIGH" in out
        assert "Levee Protection: Yes" in out
        assert "Total Zones: 3" in out
        assert "not a site-specific flood study" in out
