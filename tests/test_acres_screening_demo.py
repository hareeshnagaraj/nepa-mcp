from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = ROOT / "scripts" / "acres_screening_demo.py"


def _load_demo_module():
    spec = importlib.util.spec_from_file_location("acres_screening_demo", DEMO_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_scenario_catalog_has_required_fixture_paths() -> None:
    demo = _load_demo_module()

    assert set(demo.SCENARIOS) == {
        "pittsburgh_industrial_corridor",
        "dc_infrastructure_point",
        "sparse_rural_no_hit",
    }
    assert "pagination" in demo.SCENARIOS["pittsburgh_industrial_corridor"]["description"].lower()
    assert "no-hit" in demo.SCENARIOS["sparse_rural_no_hit"]["description"].lower()


def test_report_keeps_source_and_reviewer_caveats(monkeypatch) -> None:
    demo = _load_demo_module()

    def fake_query(latitude: float, longitude: float, buffer_miles: float):
        return {
            "center": {"latitude": latitude, "longitude": longitude},
            "buffer_miles": buffer_miles,
            "total": 2,
            "properties": [
                {
                    "name": "NEAREST SITE",
                    "city": "PITTSBURGH",
                    "county": "ALLEGHENY",
                    "state": "PA",
                    "distance_miles": 0.1,
                    "acres_property_id": "1",
                    "latitude": latitude,
                    "longitude": longitude,
                    "facility_url": "https://example.test/one",
                },
                {
                    "name": "SECOND SITE",
                    "city": "PITTSBURGH",
                    "county": "ALLEGHENY",
                    "state": "PA",
                    "distance_miles": 0.2,
                    "acres_property_id": "2",
                    "latitude": latitude,
                    "longitude": longitude,
                    "facility_url": "https://example.test/two",
                },
            ],
            "warnings": [],
            "truncated": False,
            "partial": False,
        }

    monkeypatch.setattr(demo, "get_epa_acres_properties_in_roi", fake_query)
    report = demo.build_report(scenario_slugs=["pittsburgh_industrial_corridor"], nearest_limit=1)
    scenario = report["scenarios"][0]

    assert scenario["source"]["label"] == "EPA ACRES Brownfields grant-program property records"
    assert "not a complete inventory of brownfields or contaminated sites" in report["source_caveat"]
    assert scenario["nearest_properties"][0]["name"] == "NEAREST SITE"
    assert len(scenario["nearest_properties"]) == 1
    assert any("not evidence" in caveat for caveat in scenario["review_caveats"])


def test_markdown_renders_honest_no_hit_path(monkeypatch) -> None:
    demo = _load_demo_module()

    monkeypatch.setattr(
        demo,
        "get_epa_acres_properties_in_roi",
        lambda *_args: {
            "total": 0,
            "properties": [],
            "warnings": [],
            "truncated": False,
            "partial": False,
        },
    )
    report = demo.build_report(scenario_slugs=["sparse_rural_no_hit"])
    markdown = demo.format_markdown(report)

    assert "No ACRES Brownfields grant-program property records were identified" in markdown
    assert "not a finding that the area is free of brownfields or contamination" in markdown
    assert "ACRES contains EPA Brownfields grant-program property records reported by grantees" in markdown


def test_markdown_surfaces_pagination(monkeypatch) -> None:
    demo = _load_demo_module()

    monkeypatch.setattr(
        demo,
        "get_epa_acres_properties_in_roi",
        lambda *_args: {
            "total": 11,
            "properties": [
                {
                    "name": f"SITE {i}",
                    "city": "PITTSBURGH",
                    "county": "ALLEGHENY",
                    "state": "PA",
                    "distance_miles": i / 10,
                    "acres_property_id": str(i),
                }
                for i in range(11)
            ],
            "warnings": [],
            "truncated": False,
            "partial": False,
        },
    )
    report = demo.build_report(scenario_slugs=["pittsburgh_industrial_corridor"], nearest_limit=3)
    markdown = demo.format_markdown(report)

    assert "Pagination: first 10 shown; continue with result_offset=10" in markdown
    assert "SITE 0" in markdown
    assert "SITE 3" not in markdown
