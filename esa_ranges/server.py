#!/usr/bin/env python3
"""
MCP Server for NOAA ESA Species Ranges

Queries the NOAA Fisheries Ranges_dice FeatureServer to identify
ESA-listed species ranges (with HUC-12 watershed detail) within a
Region of Interest for Section 7 ESA compliance screening in NEPA analyses.
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

from src.apis.esa_ranges_api import (
    get_esa_species_ranges_in_roi,
    format_esa_species_ranges_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("esa-ranges-mcp-server")

mcp = FastMCP("esa-ranges-server")

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


@mcp.tool(name="get_esa_species_ranges_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_esa_species_ranges_in_roi_tool(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0
) -> str:
    """Query NOAA for ESA-listed species ranges within the ROI.

    Returns ESA-listed salmon and steelhead range records from the NOAA
    Fisheries West Coast Region, broken down by HUC-12 watershed. Outside the
    West Coast Region service geography, a no-hit result may mean out-of-scope
    rather than no ESA concern. Watershed polygons are unioned by range record
    and clipped to the requested point-buffer ROI; upstream whole-watershed
    area is retained separately for provenance.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of ESA species ranges found within the ROI.

    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying ESA species ranges for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_esa_species_ranges_in_roi(latitude, longitude, buffer_miles)
    return format_esa_species_ranges_summary(result)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
