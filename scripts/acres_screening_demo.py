#!/usr/bin/env python3
"""Run EPA ACRES Brownfields screening scenarios for NEPA review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
EPA_ACRES_DIR = REPO_DIR / "epa_acres"
if str(EPA_ACRES_DIR) not in sys.path:
    sys.path.insert(0, str(EPA_ACRES_DIR))
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from src.apis.acres_api import get_epa_acres_properties_in_roi  # noqa: E402

ACRES_SOURCE_CAVEAT = (
    "ACRES contains EPA Brownfields grant-program property records reported by grantees; "
    "it is not a complete inventory of brownfields or contaminated sites."
)
REVIEW_CAVEATS = [
    ACRES_SOURCE_CAVEAT,
    "An ACRES record is not a determination that land is contaminated, available, or suitable for development.",
    "An empty ACRES result is not evidence that the project area is free of brownfields or contamination.",
    "Confirm material findings with environmental site assessments and authoritative federal, state, Tribal, and local records.",
]
DEFAULT_NEAREST_LIMIT = 5

SCENARIOS: dict[str, dict[str, Any]] = {
    "pittsburgh_industrial_corridor": {
        "title": "Pittsburgh industrial corridor",
        "description": "Dense urban-industrial corridor; useful for nearest-first review and pagination.",
        "latitude": 40.455,
        "longitude": -79.99,
        "buffer_miles": 5.0,
        "pagination_page_size": 10,
    },
    "dc_infrastructure_point": {
        "title": "DC-area infrastructure point",
        "description": "District-area infrastructure context with nearby ACRES Brownfields grant-program records.",
        "latitude": 38.8895,
        "longitude": -77.0353,
        "buffer_miles": 5.0,
        "pagination_page_size": 10,
    },
    "sparse_rural_no_hit": {
        "title": "Sparse rural no-hit path",
        "description": "Rural coordinate that should show the honest ACRES no-hit path when the source returns no records.",
        "latitude": 44.739,
        "longitude": -104.404,
        "buffer_miles": 5.0,
        "pagination_page_size": 10,
    },
}


def _nearest_properties(properties: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return properties[:limit]


def build_scenario_report(
    slug: str, scenario: dict[str, Any], *, nearest_limit: int = DEFAULT_NEAREST_LIMIT
) -> dict[str, Any]:
    """Query ACRES and return a compact NEPA screening report for one scenario."""
    result = get_epa_acres_properties_in_roi(
        scenario["latitude"],
        scenario["longitude"],
        scenario["buffer_miles"],
    )
    properties = list(result.get("properties", []))
    page_size = int(scenario.get("pagination_page_size", 10))
    pagination = {
        "page_size": page_size,
        "first_page_count": min(page_size, len(properties)),
        "has_more": len(properties) > page_size,
        "next_result_offset": page_size if len(properties) > page_size else None,
    }
    return {
        "slug": slug,
        "title": scenario["title"],
        "description": scenario["description"],
        "project_point": {
            "latitude": scenario["latitude"],
            "longitude": scenario["longitude"],
            "buffer_miles": scenario["buffer_miles"],
        },
        "acres_total": result.get("total", 0),
        "data_unavailable": bool(result.get("data_unavailable")),
        "partial": bool(result.get("partial")),
        "truncated": bool(result.get("truncated")),
        "warnings": result.get("warnings", []),
        "nearest_properties": _nearest_properties(properties, nearest_limit),
        "pagination": pagination,
        "review_caveats": REVIEW_CAVEATS,
        "source": {
            "label": "EPA ACRES Brownfields grant-program property records",
            "caveat": ACRES_SOURCE_CAVEAT,
        },
    }


def build_report(
    *, nearest_limit: int = DEFAULT_NEAREST_LIMIT, scenario_slugs: list[str] | None = None
) -> dict[str, Any]:
    """Run the selected ACRES scenarios and return the combined workflow output."""
    slugs = scenario_slugs or list(SCENARIOS)
    unknown = [slug for slug in slugs if slug not in SCENARIOS]
    if unknown:
        raise ValueError(f"Unknown scenario slug(s): {', '.join(unknown)}")
    return {
        "workflow": "EPA ACRES Brownfields screening demo",
        "source_caveat": ACRES_SOURCE_CAVEAT,
        "scenarios": [build_scenario_report(slug, SCENARIOS[slug], nearest_limit=nearest_limit) for slug in slugs],
    }


def _format_property(prop: dict[str, Any]) -> str:
    bits = [prop.get("name") or "Unknown property"]
    place = ", ".join(part for part in [prop.get("city"), prop.get("county"), prop.get("state")] if part)
    if place:
        bits.append(place)
    if prop.get("distance_miles") is not None:
        bits.append(f"{prop['distance_miles']:.3f} mi")
    if prop.get("acres_property_id"):
        bits.append(f"ACRES ID {prop['acres_property_id']}")
    return " — ".join(bits)


def format_markdown(report: dict[str, Any]) -> str:
    """Render workflow output as Markdown for agents or review packets."""
    lines = [f"# {report['workflow']}", "", f"Source caveat: {report['source_caveat']}", ""]
    for scenario in report["scenarios"]:
        point = scenario["project_point"]
        lines += [
            f"## {scenario['title']}",
            "",
            scenario["description"],
            "",
            f"Project point: {point['latitude']}, {point['longitude']} ({point['buffer_miles']} mi buffer)",
            f"ACRES records returned: {scenario['acres_total']}",
            "",
        ]
        if scenario["data_unavailable"]:
            lines += ["ACRES data were unavailable for this request; this is not a no-hit finding.", ""]
        elif scenario["nearest_properties"]:
            lines += ["Nearest ACRES Brownfields grant-program property records:"]
            lines += [f"- {_format_property(prop)}" for prop in scenario["nearest_properties"]]
            lines.append("")
        else:
            lines += [
                "No ACRES Brownfields grant-program property records were identified within the ROI buffer.",
                "This is an honest no-hit path for ACRES only, not a finding that the area is free of brownfields or contamination.",
                "",
            ]
        if scenario["pagination"]["has_more"]:
            lines += [
                f"Pagination: first {scenario['pagination']['first_page_count']} shown; continue with result_offset={scenario['pagination']['next_result_offset']} for more nearest-first records.",
                "",
            ]
        if scenario["warnings"]:
            lines += ["Warnings:", *[f"- {warning}" for warning in scenario["warnings"]], ""]
        lines += ["Reviewer caveats:", *[f"- {caveat}" for caveat in scenario["review_caveats"]], ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EPA ACRES Brownfields screening demo scenarios.")
    parser.add_argument("--json", action="store_true", help="Write JSON instead of Markdown.")
    parser.add_argument(
        "--nearest", type=int, default=DEFAULT_NEAREST_LIMIT, help="Nearest property records to show per scenario."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Scenario slug to run; repeat to select multiple.",
    )
    args = parser.parse_args()

    report = build_report(nearest_limit=args.nearest, scenario_slugs=args.scenario)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
