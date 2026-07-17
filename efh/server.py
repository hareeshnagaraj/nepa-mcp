#!/usr/bin/env python3
"""
MCP Server for NOAA Essential Fish Habitat (EFH) Data

Exposes four tools covering Habitat Areas of Particular Concern (HAPC),
general EFH areas, salmon EFH by HUC-8 watershed, and HMS/Coastal Pelagic/
Groundfish EFH. Used for Magnuson-Stevens Act compliance and ESA Section 7
consultation screening in NEPA analyses.
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

from src.apis.efh_api import (
    get_hapc_in_roi,
    format_hapc_summary,
    get_efh_areas_in_roi,
    format_efh_areas_summary,
    get_salmon_efh_in_roi,
    format_salmon_efh_summary,
    get_hms_cps_groundfish_efh_in_roi,
    format_hms_cps_groundfish_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("efh-mcp-server")

mcp = FastMCP("efh-server")

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


@mcp.tool(name="get_efh_hapc", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_efh_hapc_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA for Habitat Areas of Particular Concern (HAPC) within the ROI.

    Returns HAPC designations — subsets of EFH identified as high priority
    for conservation based on ecological importance, sensitivity to human
    activities, development stress, or rarity. HAPCs warrant heightened
    scrutiny under the Magnuson-Stevens Act. Coverage is NOAA Fisheries West
    Coast Region EFH; outside that service geography, no hits may mean out-of-scope.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of HAPC designations found within the ROI.

    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying EFH HAPC for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_hapc_in_roi(latitude, longitude, buffer_miles)
    return format_hapc_summary(result)


@mcp.tool(name="get_efh_areas", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_efh_areas_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA for Essential Fish Habitat (EFH) areas within the ROI.

    Returns general EFH designations — waters and substrate necessary for fish
    spawning, breeding, feeding, or growth to maturity as defined under the
    Magnuson-Stevens Fishery Conservation and Management Act. Coverage is NOAA
    Fisheries West Coast Region EFH; outside that service geography, no hits may
    mean out-of-scope.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of EFH areas found within the ROI.

    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying EFH areas for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_efh_areas_in_roi(latitude, longitude, buffer_miles)
    return format_efh_areas_summary(result)


@mcp.tool(name="get_efh_salmon", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_efh_salmon_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA for salmon Essential Fish Habitat by HUC-8 watershed within the ROI.

    Returns HUC-8 watersheds designated as EFH for Chinook, Coho, and Pink
    salmon in the NOAA Fisheries West Coast Region service. Identifies which
    salmon species have EFH in each watershed. Outside that geography, no hits
    may mean out-of-scope.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of salmon EFH watersheds found within the ROI.

    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying salmon EFH for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_salmon_efh_in_roi(latitude, longitude, buffer_miles)
    return format_salmon_efh_summary(result)


@mcp.tool(name="get_efh_hms_cps_groundfish", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_efh_hms_cps_groundfish_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA for HMS, Coastal Pelagic, and Groundfish EFH within the ROI.

    Returns EFH designations for Highly Migratory Species (tunas, sharks,
    swordfish), Coastal Pelagic Species (sardine, anchovy, mackerel), and
    Pacific Coast Groundfish (rockfish, flatfish, roundfish) from NOAA Fisheries
    West Coast Region EFH services. Outside that geography, no hits may mean
    out-of-scope. Polygon acreage is unioned by designation and clipped to the
    requested point-buffer ROI; source feature acreage is retained separately.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of HMS/CPS/Groundfish EFH found within the ROI.

    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying HMS/CPS/Groundfish EFH for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_hms_cps_groundfish_efh_in_roi(latitude, longitude, buffer_miles)
    return format_hms_cps_groundfish_summary(result)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
