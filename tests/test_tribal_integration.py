"""
Integration tests for the tribal MCP server.

These load ``tribal/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
layer mocked. Mirrors the loading approach in ``test_usace_integration.py``.
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
SERVER_DIR = ROOT / "tribal"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {"get_tribal_lands_in_roi"}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_tribal_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_tribal_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_tribal_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(module, feature_map, warnings=None):
    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.query_features = staticmethod(query_features)


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        result = await client.call_tool(tool_name, args)
    return result


def _text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class TestToolRegistration:
    def test_tool_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestTribalLandsTool:
    def test_returns_markdown_with_tribal_land(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {
                "Federal American Indian Reservations": [
                    {"attributes": {"NAME": "Navajo Nation Reservation", "AREALAND": 2589988.11}}
                ]
            },
        )
        result = asyncio.run(
            _call(module, "get_tribal_lands_in_roi", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25})
        )
        text = _text(result)
        assert "Tribal Lands within ROI" in text
        assert "Navajo Nation Reservation" in text
        assert "Federal American Indian Reservations (1):" in text

    def test_empty_result_is_graceful(self, monkeypatch):
        module = _load_server()
        _install_mock_query(module, {})
        result = asyncio.run(_call(module, "get_tribal_lands_in_roi", {"latitude": 34.5, "longitude": -106.5}))
        assert "No tribal land records were returned." in _text(result)

    def test_multiple_categories_rendered(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {
                "Federal American Indian Reservations": [{"attributes": {"NAME": "Fed Res"}}],
                "Hawaiian Home Lands": [{"attributes": {"NAME": "HHL"}}],
            },
        )
        result = asyncio.run(_call(module, "get_tribal_lands_in_roi", {"latitude": 34.5, "longitude": -106.5}))
        text = _text(result)
        assert "Federal American Indian Reservations (1):" in text
        assert "Hawaiian Home Lands (1):" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_tribal_lands_in_roi", {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(module, "get_tribal_lands_in_roi", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0})
            )
