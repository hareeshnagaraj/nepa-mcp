#!/usr/bin/env python3
"""
MCP Server for EPA NEPA Assist Environmental Screening

Provides EPA NEPAssist screening for NEPA compliance.
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

from src.apis.nepa_assist_api import query_nepa_assist, format_nepa_assist_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nepa-assist-mcp-server")

mcp = FastMCP("nepa-assist-server")

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


@mcp.tool(name="analyze_nepa_assist_screening", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def nepa_assist_screening(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0, project_title: str = ""
) -> str:
    """Analyze EPA NEPAssist environmental screening layers for a location.

    Returns mapped screening indicators including air quality, water resources,
    contaminated sites, natural resources, and cultural resources where available.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles around the point, valid range 0.1 to 100.0 (default: 25).
        project_title: Optional project title/name for the screening
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Performing NEPA Assist screening for (%s, %s)", latitude, longitude)

    results = query_nepa_assist(latitude, longitude, buffer_miles, project_title)
    return format_nepa_assist_report(results)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
