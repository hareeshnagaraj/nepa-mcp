#!/usr/bin/env python3
"""
MCP Server for NOAA West Coast Region Critical Habitat

Queries NOAA Fisheries ArcGIS FeatureServer to identify ESA-designated
critical habitat within a Region of Interest for Section 7 ESA compliance
screening in NEPA analyses.
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

# Add the server directory to path for local imports
SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pydantic import Field

from fastmcp import FastMCP

from src.apis.noaa_api import (
    get_noaa_critical_habitat_in_roi,
    format_noaa_critical_habitat_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("noaa-mcp-server")

mcp = FastMCP("noaa-server")

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


@mcp.tool(name="get_noaa_critical_habitat_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_noaa_critical_habitat_in_roi_tool(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0
) -> str:
    """Query NOAA for West Coast Region ESA critical habitat within the ROI.

    Queries the NOAA Fisheries ArcGIS FeatureServer for designated critical
    habitat (lines and polygons) under the Endangered Species Act. Covers
    NOAA-managed species including salmon, steelhead, marine mammals, and
    marine fish within the West Coast Region service. Outside that service
    geography, a no-hit result may mean out-of-scope rather than no ESA concern.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of NOAA critical habitat found within the ROI.

    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying NOAA critical habitat for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_noaa_critical_habitat_in_roi(latitude, longitude, buffer_miles)
    return format_noaa_critical_habitat_summary(result)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
