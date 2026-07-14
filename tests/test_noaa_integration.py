"""
Integration tests for the NOAA critical habitat MCP server.

These load ``noaa/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
layer mocked. This mirrors the loading approach in ``test_usace_integration.py``.

The server exposes a single ROI-AREA tool: ``get_noaa_critical_habitat_in_roi``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "noaa"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAME = "get_noaa_critical_habitat_in_roi"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_noaa_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_noaa_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_noaa_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _polygon_feature(*, entity="Test whale DPS", unit="Unit A", area=99_999.0, geometry=SIMPLE_GEOMETRY):
    feature = {
        "attributes": {
            "comname": "Test whale",
            "sciename": "Testus whaleus",
            "listentity": entity,
            "liststatus": "Endangered",
            "unit": unit,
            "taxon": "Marine mammal",
            "areasqkm": area,
            "frn": "80 FR 1234",
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _line_feature(*, entity="Test salmon DPS", length=12.5):
    return {
        "attributes": {
            "comname": "Test salmon",
            "sciename": "Testus salmonus",
            "listentity": entity,
            "liststatus": "Threatened",
            "unit": "River Reach",
            "taxon": "Fish",
            "lengthkm": length,
        }
    }


def _install_mock_query(layer_features, warnings=None):
    """Patch ArcGISService with a per-layer feature map (keyed by layer_id)."""
    from nepa_mcp_common.arcgis import ArcGISService

    def query_features(_url, layer_id, _geometry, **_kwargs):
        feats = layer_features.get(layer_id, [])
        return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.query_features = staticmethod(query_features)


async def _call(module, args):
    async with Client(module.mcp) as client:
        result = await client.call_tool(_TOOL_NAME, args)
    return result


def _text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class TestToolRegistration:
    def test_single_tool_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        names = asyncio.run(_names())
        assert _TOOL_NAME in names


class TestPolygonHabitatTool:
    def test_reports_clipped_area_and_source_provenance(self):
        module = _load_server()
        _install_mock_query({2: [_polygon_feature(area=99_999.0)]})
        result = asyncio.run(_call(module, {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 5}))
        text = _text(result)
        assert "NOAA Critical Habitat (West Coast Region)" in text
        assert "Test whale DPS" in text
        assert "Area within ROI:" in text
        assert "Source feature-area total (not clipped to ROI):" in text
        assert "80 FR 1234" in text

    def test_default_buffer_used_when_omitted(self):
        module = _load_server()
        _install_mock_query({2: [_polygon_feature(area=10.0)]})
        result = asyncio.run(_call(module, {"latitude": 46.5, "longitude": -120.5}))
        text = _text(result)
        assert "Buffer:** 25.0 miles" in text


class TestLineHabitatTool:
    def test_line_layer_length_surfaces_without_area(self):
        module = _load_server()
        _install_mock_query({1: [_line_feature(length=12.5)]})
        result = asyncio.run(_call(module, {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 5}))
        text = _text(result)
        assert "Test salmon DPS" in text
        assert "Intersecting line-feature length (source attribute): 12.5 km" in text


class TestEmptyResult:
    def test_no_habitat_is_graceful(self):
        module = _load_server()
        _install_mock_query({})
        result = asyncio.run(_call(module, {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 5}))
        assert "No NOAA West Coast Region critical habitat was identified" in _text(result)

    def test_out_of_coverage_point_flags_warning(self):
        module = _load_server()
        # A Chicago-area buffer geometry is far outside the West Coast Region
        # service, and the empty result should be flagged accordingly.
        chicago = {
            "rings": [[[-88.0, 41.5], [-87.0, 41.5], [-87.0, 42.0], [-88.0, 42.0], [-88.0, 41.5]]],
            "spatialReference": {"wkid": 4326},
        }
        from nepa_mcp_common.arcgis import ArcGISService

        ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: chicago)
        ArcGISService.query_features = staticmethod(
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[])
        )
        result = asyncio.run(_call(module, {"latitude": 41.8, "longitude": -87.6, "buffer_miles": 5}))
        text = _text(result)
        assert "outside the expected geographic coverage" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, {"latitude": 999, "longitude": -120.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 0}))
