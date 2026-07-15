from __future__ import annotations

import ast
import copy
import importlib
import inspect
import json
import stat
from pathlib import Path

import pytest

from nepa_mcp.loader import load_server_module


ROOT = Path(__file__).resolve().parents[1]


def _load_map_modules():
    server = load_server_module("map_composer")
    collector = importlib.import_module("src.core.geometry_collector")
    renderer = importlib.import_module("src.core.map_renderer")
    return server, collector, renderer


@pytest.fixture
def minimal_layers_data() -> dict:
    return {
        "roi": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.8]},
                    "properties": {"type": "Project Location"},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-77.1, 38.7],
                                [-76.9, 38.7],
                                [-76.9, 38.9],
                                [-77.1, 38.9],
                                [-77.1, 38.7],
                            ]
                        ],
                    },
                    "properties": {"type": "Region of Interest", "buffer_miles": 5},
                },
            ],
        },
        "counties": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.8]},
                    "properties": {"name": "District of Columbia", "state": "11", "fips": "11001"},
                }
            ],
        },
    }


def test_layer_metadata_profiles_and_sources_are_consistent() -> None:
    server, collector, _ = _load_map_modules()

    expected = set(collector.DEFAULT_LAYERS)
    assert len(expected) == 32
    assert set(server.LAYER_METADATA) == expected
    assert set(server.LAYER_SOURCE_URLS) == expected
    assert set(collector.LAYER_PROFILES) == {
        "screening",
        "biological",
        "water",
        "lands",
        "full",
    }
    assert collector.LAYER_PROFILES["full"] == collector.DEFAULT_LAYERS
    assert all(set(layers) <= expected for layers in collector.LAYER_PROFILES.values())


def test_layer_selection_rejects_unknown_and_empty_values() -> None:
    server, _, _ = _load_map_modules()

    assert server._resolve_layers("water", ["roi", "roi", "nhd_lakes"]) == [
        "roi",
        "nhd_lakes",
    ]
    with pytest.raises(ValueError, match="At least one"):
        server._resolve_layers("screening", [])
    with pytest.raises(ValueError, match="Unknown Map Composer"):
        server._resolve_layers("screening", ["not_a_layer"])


def test_comprehensive_profile_is_the_tool_default() -> None:
    server, collector, _ = _load_map_modules()

    compose_parameters = inspect.signature(server.compose_environmental_map).parameters
    export_parameters = inspect.signature(server.export_all_layers_geojson).parameters

    assert compose_parameters["profile"].default == "full"
    assert export_parameters["profile"].default == "full"
    assert server._resolve_layers("full", None) == collector.DEFAULT_LAYERS


@pytest.mark.parametrize(
    ("buffer_miles", "expected_zoom"),
    [(1, 13), (5, 12), (10, 11), (25, 10), (50, 9), (100, 8)],
)
def test_initial_zoom_tracks_buffer_size(buffer_miles: float, expected_zoom: int) -> None:
    server, _, _ = _load_map_modules()
    assert server._zoom_start_for_buffer(buffer_miles) == expected_zoom


def test_artifacts_use_private_operator_controlled_directory(tmp_path: Path, monkeypatch) -> None:
    server, _, _ = _load_map_modules()
    configured = tmp_path / "private-artifacts"
    monkeypatch.setenv("NEPA_MCP_OUTPUT_DIR", str(configured))

    directory = server._artifact_directory()
    first = server._artifact_path(
        prefix="map",
        suffix=".html",
        latitude=38.9,
        longitude=-77.0,
        buffer_miles=5,
    )
    second = server._artifact_path(
        prefix="map",
        suffix=".html",
        latitude=38.9,
        longitude=-77.0,
        buffer_miles=5,
    )

    assert directory == configured.resolve()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert first.parent == directory
    assert first != second


def test_collection_distinguishes_failed_empty_and_successful_layers(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    monkeypatch.setattr(
        collector.ArcGISService,
        "create_roi_buffer",
        lambda *_args: {"rings": [[[-77, 38], [-76, 38], [-76, 39], [-77, 38]]]},
    )
    monkeypatch.setattr(
        collector,
        "get_roi_geojson",
        lambda *_args: {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None, "properties": {}}],
        },
    )
    monkeypatch.setattr(
        collector,
        "get_critical_habitat_geojson",
        lambda *_args: collector._failed_feature_collection("service unavailable"),
    )
    monkeypatch.setattr(
        collector,
        "get_wildlife_refuges_geojson",
        lambda *_args: {"type": "FeatureCollection", "features": []},
    )

    result = collector.collect_all_layers(
        38.9,
        -77.0,
        5,
        ["roi", "critical_habitat", "wildlife_refuges"],
    )

    assert result.statuses["roi"]["status"] == "ok"
    assert result.statuses["critical_habitat"] == {
        "status": "failed",
        "feature_count": 0,
        "warnings": ["service unavailable"],
    }
    assert result.statuses["wildlife_refuges"]["status"] == "empty"
    assert "service unavailable" in result.warnings


def test_collection_converts_fetcher_exception_to_failed_status(monkeypatch, capsys) -> None:
    _, collector, _ = _load_map_modules()
    monkeypatch.setattr(
        collector.ArcGISService,
        "create_roi_buffer",
        lambda *_args: {"rings": [[[-77, 38], [-76, 38], [-76, 39], [-77, 38]]]},
    )

    def fail(*_args):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(collector, "get_roi_geojson", fail)
    result = collector.collect_all_layers(38.9, -77.0, 5, ["roi"])

    assert result.statuses["roi"]["status"] == "failed"
    assert "upstream timeout" in result.statuses["roi"]["warnings"][0]
    assert capsys.readouterr().out == ""


def test_arcgis_error_payload_is_not_treated_as_an_empty_layer() -> None:
    _, collector, _ = _load_map_modules()
    with pytest.raises(RuntimeError, match="Service unavailable: retry later"):
        collector._raise_for_arcgis_error(
            {
                "error": {
                    "message": "Service unavailable",
                    "details": ["retry later"],
                }
            }
        )


def test_optional_species_enrichment_warning_marks_counties_partial(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {
                        "attributes": {
                            "NAME": "Example County",
                            "BASENAME": "Example",
                            "STATE": "11",
                            "GEOID": "11001",
                        },
                        "geometry": {
                            "rings": [
                                [
                                    [-77.1, 38.7],
                                    [-76.9, 38.7],
                                    [-76.9, 38.9],
                                    [-77.1, 38.7],
                                ]
                            ]
                        },
                    }
                ]
            }

    monkeypatch.setattr(collector.requests, "post", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        collector,
        "_enrich_counties_with_species",
        lambda *_args, **_kwargs: ["GBIF enrichment unavailable"],
    )

    result = collector.get_counties_geojson(
        {"rings": [[[-77.1, 38.7], [-76.9, 38.7], [-76.9, 38.9], [-77.1, 38.7]]]},
        include_species_data=True,
        latitude=38.8,
        longitude=-77.0,
        buffer_miles=5,
    )

    assert result["status"] == "partial"
    assert result["warnings"] == ["GBIF enrichment unavailable"]
    assert len(result["features"]) == 1


def test_arcgis_spatial_queries_use_post_bodies(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": []}

    def post(url, *, data, timeout):
        captured.update(url=url, data=data, timeout=timeout)
        return Response()

    monkeypatch.setattr(collector.requests, "post", post)
    result = collector._post_arcgis_json(
        "https://example.test/FeatureServer/0/query",
        {"geometry": "large-polygon", "f": "json"},
        timeout=30,
    )

    assert result == {"features": []}
    assert captured == {
        "url": "https://example.test/FeatureServer/0/query",
        "data": {"geometry": "large-polygon", "f": "json"},
        "timeout": 30,
    }


def test_arcgis_spatial_queries_retry_transient_failures(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    attempts = 0
    delays = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": []}

    def post(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise collector.requests.Timeout("temporary timeout")
        return Response()

    monkeypatch.setattr(collector.requests, "post", post)
    monkeypatch.setattr(collector.time, "sleep", delays.append)

    result = collector._post_arcgis_json(
        "https://example.test/FeatureServer/0/query",
        {"geometry": "large-polygon", "f": "json"},
        timeout=30,
    )

    assert result == {"features": []}
    assert attempts == 2
    assert delays == [0.25]


def test_drifted_service_contracts_are_current(monkeypatch) -> None:
    server, collector, _ = _load_map_modules()
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": []}

    def post(url, *, data, timeout):
        calls.append((url, data, timeout))
        return Response()

    monkeypatch.setattr(collector.requests, "post", post)
    polygon = {
        "rings": [[[-77.1, 38.7], [-76.9, 38.7], [-76.9, 38.9], [-77.1, 38.7]]],
        "spatialReference": {"wkid": 4326},
    }

    collector.get_usace_districts_geojson(polygon)
    collector.get_nps_boundaries_geojson(polygon)
    collector.get_fire_perimeters_geojson(polygon)

    assert "usace_cw_districts" in calls[0][0]
    assert server.LAYER_SOURCE_URLS["usace_districts"] in calls[0][0]
    assert calls[1][1]["outFields"] == "UNIT_NAME,UNIT_CODE,UNIT_TYPE,STATE,REGION"
    assert "GNIS_ID" not in calls[1][1]["outFields"]
    assert "InterAgencyFirePerimeterHistory_All_Years_View" in calls[2][0]
    assert calls[2][1]["outFields"] == "INCIDENT,FIRE_YEAR_INT,FIRE_YEAR,FEATURE_CA,GIS_ACRES,AGENCY,SOURCE"


def test_renderer_escapes_title_feature_values_and_unsafe_links(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    malicious = "</div><script>alert('xss')</script>"
    data = copy.deepcopy(minimal_layers_data)
    data["counties"]["features"][0]["properties"]["name"] = malicious
    data["usace_districts"] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-77.0, 38.8]},
                "properties": {
                    "name": "District",
                    "website_url": "javascript:alert(1)",
                },
            }
        ],
    }

    output = tmp_path / "map.html"
    renderer.render_environmental_map(
        data,
        38.8,
        -77.0,
        str(output),
        title=malicious,
    )
    html = output.read_text(encoding="utf-8")

    assert malicious not in html
    assert "href='javascript:" not in html
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_renderer_exposes_layer_availability_summary(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    output = tmp_path / "status-map.html"

    renderer.render_environmental_map(
        minimal_layers_data,
        38.8,
        -77.0,
        str(output),
        title="Status map",
        layer_statuses={
            "roi": {"status": "ok", "feature_count": 2, "warnings": []},
            "counties": {"status": "partial", "feature_count": 1, "warnings": ["truncated"]},
            "critical_habitat": {"status": "empty", "feature_count": 0, "warnings": []},
            "nps_boundaries": {"status": "failed", "feature_count": 0, "warnings": ["unavailable"]},
        },
    )

    html = output.read_text(encoding="utf-8")
    assert 'aria-label="Map layer status"' in html
    assert "4 requested" in html
    assert "2 rendered (1 partial)" in html
    assert "1 empty" in html
    assert "1 failed" in html


def test_map_defaults_to_cartodb_without_redundant_legend(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    server, _, renderer = _load_map_modules()
    output = tmp_path / "default-map.html"

    renderer.render_environmental_map(
        minimal_layers_data,
        38.8,
        -77.0,
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    tool_parameters = inspect.signature(server.compose_environmental_map).parameters
    renderer_parameters = inspect.signature(renderer.render_environmental_map).parameters

    assert tool_parameters["basemap"].default == "CartoDB Positron"
    assert renderer_parameters["basemap"].default == "CartoDB Positron"
    assert "include_legend" not in tool_parameters
    assert "include_legend" not in renderer_parameters
    assert "basemaps.cartocdn.com/light_all" in html
    assert "Map Legend" not in html


def test_geojson_export_is_atomic_provenance_rich_and_non_mutating(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    original = copy.deepcopy(minimal_layers_data)
    output = tmp_path / "layers.geojson"

    result = renderer.export_combined_geojson(
        minimal_layers_data,
        str(output),
        collection_metadata={
            "profile": "screening",
            "layers": {"roi": {"status": "ok"}},
        },
    )

    exported = json.loads(output.read_text(encoding="utf-8"))
    assert result == str(output)
    assert exported["metadata"]["profile"] == "screening"
    assert exported["metadata"]["layers"]["roi"]["status"] == "ok"
    assert exported["metadata"]["feature_count"] == 3
    assert {feature["properties"]["layer"] for feature in exported["features"]} == {
        "roi",
        "counties",
    }
    assert minimal_layers_data == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not output.with_suffix(".geojson.tmp").exists()


def test_all_direct_requests_calls_declare_timeouts() -> None:
    source_paths = [
        ROOT / "map_composer" / "src" / "core" / "geometry_collector.py",
        ROOT / "map_composer" / "src" / "apis" / "counties_api.py",
        ROOT / "map_composer" / "src" / "apis" / "gbif_api.py",
    ]

    missing = []
    for path in source_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                node.func.attr in {"get", "post"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "requests"
                and not any(keyword.arg == "timeout" for keyword in node.keywords)
            ):
                missing.append(f"{path.name}:{node.lineno}")

    assert missing == []
