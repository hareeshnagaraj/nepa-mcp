#!/usr/bin/env python3
"""
MCP Server for Core GIS/ROI Functionality

Provides ROI generation and area calculations.
"""

import logging
import json
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

from src.apis.roi_api import calculate_roi_area, get_roi_geojson, format_roi_summary, format_area_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gis-mcp-server")

mcp = FastMCP("gis-server")

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
BufferMiles = Annotated[
    float,
    Field(
        ge=MIN_DISTANCE_MILES,
        le=MAX_DISTANCE_MILES,
        description="Buffer distance in miles, valid range 0.1 to 100.0.",
    ),
]


def _validate_geo_inputs(
    latitude: Latitude,
    longitude: Longitude,
    distance_miles: float,
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
            f"buffer_miles must be between {MIN_DISTANCE_MILES} and {MAX_DISTANCE_MILES} miles, got {distance_miles}"
        )

    return lat, lon, distance


@mcp.tool(name="summarize_roi_buffer", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def summarize_roi_buffer(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0, project_name: str | None = None
) -> str:
    """Generate a human-readable ROI summary from lat/lon with a configurable buffer.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
        project_name: Optional project identifier
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Generating ROI for (%s, %s) at %s mi", latitude, longitude, buffer_miles)

    geojson = get_roi_geojson(latitude, longitude, buffer_miles)
    area = geojson.get("metadata", {}).get("area", {})
    sq_miles = area.get("square_miles", 0)
    acres = area.get("acres", 0)

    return format_roi_summary(latitude, longitude, buffer_miles, sq_miles, acres, geojson, project_name)


@mcp.tool(name="get_roi_geojson", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_roi_geojson_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Return ROI GeoJSON for the requested buffer as formatted JSON.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Fetching ROI GeoJSON for (%s, %s) at %s mi", latitude, longitude, buffer_miles)

    geojson = get_roi_geojson(latitude, longitude, buffer_miles)
    return json.dumps(geojson, indent=2)


@mcp.tool(name="calculate_roi_area", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def calculate_roi_area_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Compute ROI area in square miles and acres for a given buffer.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Calculating ROI area for (%s, %s) at %s mi", latitude, longitude, buffer_miles)

    sq_miles, acres = calculate_roi_area(latitude, longitude, buffer_miles)

    return format_area_summary(latitude, longitude, buffer_miles, sq_miles, acres)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
