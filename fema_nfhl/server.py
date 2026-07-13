#!/usr/bin/env python3
"""
MCP Server for FEMA National Flood Hazard Layer (NFHL)

Provides tools for flood zone, levee, and water area data queries.
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pydantic import Field

from fastmcp import FastMCP

from src.apis.fema_nfhl_api import (
    get_flood_zones,
    get_levees,
    get_water_areas,
    analyze_flood_risk,
    format_flood_zones_summary,
    format_levees_summary,
    format_water_areas_summary,
    format_flood_risk_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fema-nfhl-mcp-server")

mcp = FastMCP("fema-nfhl-server")

READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
MIN_DISTANCE_MILES = 0.1
MAX_DISTANCE_MILES = 100.0

Latitude = Annotated[
    float,
    Field(
        ge=-90,
        le=90,
        description="Latitude in decimal degrees (WGS84), valid range -90 to 90.",
    ),
]
Longitude = Annotated[
    float,
    Field(
        ge=-180,
        le=180,
        description="Longitude in decimal degrees (WGS84), valid range -180 to 180.",
    ),
]
RadiusMiles = Annotated[
    float,
    Field(
        ge=MIN_DISTANCE_MILES,
        le=MAX_DISTANCE_MILES,
        description="Search radius in miles, valid range 0.1 to 100.0.",
    ),
]


def _validate_geo_inputs(
    latitude: Latitude,
    longitude: Longitude,
    distance_miles: float,
    distance_name: str,
) -> tuple[float, float, float]:
    """Validate common geospatial tool arguments before upstream calls."""
    try:
        lat = float(latitude)
        lon = float(longitude)
        distance = float(distance_miles)
    except (TypeError, ValueError) as exc:
        raise ValueError("latitude, longitude, and distance arguments must be numeric") from exc

    if not -90 <= lat <= 90:
        raise ValueError(f"latitude must be between -90 and 90, got {latitude}")
    if not -180 <= lon <= 180:
        raise ValueError(f"longitude must be between -180 and 180, got {longitude}")
    if not MIN_DISTANCE_MILES <= distance <= MAX_DISTANCE_MILES:
        raise ValueError(
            f"{distance_name} must be between {MIN_DISTANCE_MILES} and {MAX_DISTANCE_MILES} miles, got {distance_miles}"
        )

    return lat, lon, distance


@mcp.tool(name="get_fema_nfhl_flood_zones_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_flood_zones_tool(latitude: Latitude, longitude: Longitude, radius_miles: RadiusMiles = 25.0) -> str:
    """Query FEMA flood hazard zones within a radius of a location.

    Returns flood zone classifications (Zone A, AE, X, D, etc.).

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        radius_miles: Search radius in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, radius_miles = _validate_geo_inputs(latitude, longitude, radius_miles, "radius_miles")
    logger.info("Querying FEMA flood zones for (%s, %s)", latitude, longitude)
    data = get_flood_zones(latitude, longitude, radius_miles)
    return format_flood_zones_summary(data)


@mcp.tool(name="get_fema_nfhl_levees_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_levees_tool(latitude: Latitude, longitude: Longitude, radius_miles: RadiusMiles = 25.0) -> str:
    """Query FEMA levee locations within a radius of a location.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        radius_miles: Search radius in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, radius_miles = _validate_geo_inputs(latitude, longitude, radius_miles, "radius_miles")
    logger.info("Querying FEMA levees for (%s, %s)", latitude, longitude)
    data = get_levees(latitude, longitude, radius_miles)
    return format_levees_summary(data)


@mcp.tool(name="get_fema_nfhl_water_areas_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_water_areas_tool(latitude: Latitude, longitude: Longitude, radius_miles: RadiusMiles = 25.0) -> str:
    """Query FEMA water areas (rivers, lakes, etc.) within a radius.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        radius_miles: Search radius in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, radius_miles = _validate_geo_inputs(latitude, longitude, radius_miles, "radius_miles")
    logger.info("Querying FEMA water areas for (%s, %s)", latitude, longitude)
    data = get_water_areas(latitude, longitude, radius_miles)
    return format_water_areas_summary(data)


@mcp.tool(name="analyze_fema_nfhl_flood_hazard_screening", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def analyze_flood_risk_tool(latitude: Latitude, longitude: Longitude, radius_miles: RadiusMiles = 25.0) -> str:
    """Screen FEMA NFHL flood-hazard layers for a location.

    Combines flood zones, levees, and water areas into a screening summary.
    Use this for a one-shot overview; use the individual get_* tools when only
    one FEMA NFHL layer is needed.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        radius_miles: Search radius in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, radius_miles = _validate_geo_inputs(latitude, longitude, radius_miles, "radius_miles")
    logger.info("Performing FEMA NFHL flood-hazard screening for (%s, %s)", latitude, longitude)
    data = analyze_flood_risk(latitude, longitude, radius_miles)
    return format_flood_risk_summary(data)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
