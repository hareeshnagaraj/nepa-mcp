#!/usr/bin/env python3
"""
MCP Server for NOAA PCSRF (Pacific Coastal Salmon Recovery Fund) Data

Exposes four tools covering ESA-listed species ranges, critical habitat,
essential fish habitat (EFH), and PCSRF salmon recovery projects.
Used for ESA Section 7 consultation and Magnuson-Stevens Act compliance
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

from src.apis.pcsrf_api import (
    get_species_ranges_in_roi,
    format_species_ranges_summary,
    get_critical_habitat_in_roi,
    format_critical_habitat_summary,
    get_efh_in_roi,
    format_efh_summary,
    get_pcsrf_projects_in_roi,
    format_pcsrf_projects_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pcsrf-mcp-server")

mcp = FastMCP("pcsrf-server")

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


@mcp.tool(name="get_noaa_all_species_ranges_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_pcsrf_species_ranges_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA All_Species_Ranges records within the ROI.

    Returns NOAA Fisheries all-species range records. This is not PCSRF project
    data; use the PCSRF projects tool for recovery-fund project locations.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of NOAA species ranges found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying NOAA all-species ranges for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_species_ranges_in_roi(latitude, longitude, buffer_miles)
    return format_species_ranges_summary(result)


@mcp.tool(name="get_noaa_critical_habitat_20210904_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_pcsrf_critical_habitat_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA critical-habitat snapshot records within the ROI.

    Returns designated critical habitat (polygons and lines) for NOAA-managed
    species from the 2021-09-04 generalized NOAA critical-habitat services.
    Use current agency sources to confirm designations before relying on results.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of critical habitat records found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info(
        "Querying NOAA critical habitat snapshot for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles
    )
    result = get_critical_habitat_in_roi(latitude, longitude, buffer_miles)
    return format_critical_habitat_summary(result)


@mcp.tool(name="get_atlantic_salmon_efh_hapc_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_pcsrf_efh_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query Atlantic salmon EFH/HAPC buffers within the ROI.

    Returns Atlantic salmon Essential Fish Habitat and Habitat Areas of
    Particular Concern (HAPC) buffer zones. This is an Atlantic salmon dataset,
    not Pacific salmon or PCSRF project data.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of Atlantic salmon EFH/HAPC areas found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying Atlantic salmon EFH/HAPC for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_efh_in_roi(latitude, longitude, buffer_miles)
    return format_efh_summary(result)


@mcp.tool(name="get_pcsrf_projects_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_pcsrf_projects_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Query NOAA for PCSRF salmon recovery projects within the ROI.

    Returns Pacific Coastal Salmon Recovery Fund projects including
    restoration activities, monitoring, and habitat improvement projects.
    Useful for understanding existing conservation efforts in the area.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of PCSRF projects found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying PCSRF projects for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_pcsrf_projects_in_roi(latitude, longitude, buffer_miles)
    return format_pcsrf_projects_summary(result)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
