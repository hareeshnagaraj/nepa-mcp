from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"features": []}


def _arcgis_service():
    from nepa_mcp_common.arcgis import ArcGISService

    return ArcGISService


def test_query_features_posts_simplified_geometry(monkeypatch) -> None:
    ArcGISService = _arcgis_service()
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, *, data: dict[str, Any], timeout: Any, headers: dict[str, str] | None):
        calls.append({"url": url, "data": data, "timeout": timeout, "headers": headers})
        return _FakeResponse()

    def fake_get(*args, **kwargs):
        raise AssertionError("query_features should use POST, not GET")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    geometry = {
        "rings": [
            [
                [-1.0, 0.0],
                [-0.5, 0.0],
                [0.0, 0.0],
                [0.5, 0.0],
                [1.0, 0.0],
                [1.0, 0.5],
                [1.0, 1.0],
                [0.5, 1.0],
                [0.0, 1.0],
                [-0.5, 1.0],
                [-1.0, 1.0],
                [-1.0, 0.5],
                [-1.0, 0.0],
            ]
        ],
        "spatialReference": {"wkid": 4326},
    }

    ArcGISService.query_features(
        "https://example.test/FeatureServer",
        3,
        geometry,
        out_fields="NAME",
        timeout=12,
        headers={"X-Test": "1"},
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://example.test/FeatureServer/3/query"
    assert call["timeout"] == 12
    assert call["headers"] == {"X-Test": "1"}

    data = call["data"]
    assert data["outFields"] == "NAME"
    assert data["resultOffset"] == 0
    assert data["resultRecordCount"] == ArcGISService.DEFAULT_PAGE_SIZE

    posted_geometry = json.loads(data["geometry"])
    assert posted_geometry["spatialReference"] == {"wkid": 4326}
    assert len(posted_geometry["rings"][0]) < len(geometry["rings"][0])


def test_query_features_can_skip_simplification(monkeypatch) -> None:
    ArcGISService = _arcgis_service()
    posted_data: dict[str, Any] = {}

    def fake_post(url: str, *, data: dict[str, Any], timeout: Any, headers: dict[str, str] | None):
        posted_data.update(data)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    geometry = {
        "rings": [
            [
                [-1.0, 0.0],
                [-0.5, 0.0],
                [0.0, 0.0],
                [0.5, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [-1.0, 1.0],
                [-1.0, 0.0],
            ]
        ],
        "spatialReference": {"wkid": 4326},
    }

    ArcGISService.query_features(
        "https://example.test/FeatureServer",
        0,
        geometry,
        out_fields="*",
        simplify_geometry=False,
    )

    assert json.loads(posted_data["geometry"]) == geometry


def test_query_features_requests_geometry_crs_and_preserves_response_crs(monkeypatch) -> None:
    ArcGISService = _arcgis_service()
    posted_data: dict[str, Any] = {}

    class _GeometryResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "spatialReference": {"wkid": 4326},
                "features": [
                    {
                        "attributes": {"NAME": "example"},
                        "geometry": {"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]},
                    }
                ],
            }

    def fake_post(url: str, *, data: dict[str, Any], timeout: Any, headers: dict[str, str] | None):
        posted_data.update(data)
        return _GeometryResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    geometry = {
        "rings": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]],
        "spatialReference": {"wkid": 4326},
    }

    result = ArcGISService.query_features(
        "https://example.test/FeatureServer",
        0,
        geometry,
        out_fields="NAME",
        return_geometry=True,
        out_sr=4326,
    )

    assert posted_data["returnGeometry"] is True
    assert posted_data["outSR"] == 4326
    assert result.features[0]["geometry"]["spatialReference"] == {"wkid": 4326}


def test_query_features_exact_safety_cap_is_complete_without_more_records(monkeypatch) -> None:
    ArcGISService = _arcgis_service()

    class _ExactCapResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "features": [{"attributes": {"id": 1}}, {"attributes": {"id": 2}}],
                "exceededTransferLimit": False,
            }

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: _ExactCapResponse())

    result = ArcGISService.query_features(
        "https://example.test/FeatureServer",
        0,
        {"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]},
        out_fields="id",
        page_size=2,
        max_features=2,
    )

    assert len(result.features) == 2
    assert result.truncated is False
    assert result.warnings == []
