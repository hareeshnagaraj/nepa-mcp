#!/usr/bin/env python3
"""
MCP Server for USACE (U.S. Army Corps of Engineers) Regulatory Data

Provides tools for Section 404 Clean Water Act compliance analysis.
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

from src.apis.usace_api import (
    get_usace_regulatory_district,
    get_wetland_regions_in_roi,
    get_wetland_subregions_in_roi,
    analyze_usace_jurisdiction,
    format_usace_districts_summary,
    format_wetland_regions_summary,
    format_wetland_subregions_summary,
    format_comprehensive_analysis_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("usace-mcp-server")

mcp = FastMCP("usace-server")

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


@mcp.tool(name="get_usace_regulatory_district", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_usace_regulatory_district_tool(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0
) -> str:
    """Identify which USACE district has regulatory jurisdiction over the ROI.

    Returns USACE district information including district name, abbreviation,
    division, and website URL for permit inquiries.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying USACE districts for (%s, %s)", latitude, longitude)
    data = get_usace_regulatory_district(latitude, longitude, buffer_miles)
    return format_usace_districts_summary(data)


@mcp.tool(name="get_usace_wetland_regions_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_wetland_regions_in_roi_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Get wetland delineation regions within the ROI.

    Returns the broad USACE Regional Supplement regions used for wetland
    delineation methodology. Use the subregions tool when MLRA-scale detail
    nested under the regional supplement is needed.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying wetland regions for (%s, %s)", latitude, longitude)
    data = get_wetland_regions_in_roi(latitude, longitude, buffer_miles)
    return format_wetland_regions_summary(data)


@mcp.tool(name="get_usace_wetland_subregions_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_wetland_subregions_in_roi_tool(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0
) -> str:
    """Get wetland subregion classifications within the ROI.

    Returns finer MLRA-based subregions nested under USACE Regional Supplement
    regions. Use the wetland regions tool when only the applicable Regional
    Supplement is needed.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of wetland subregions found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying wetland subregions for (%s, %s)", latitude, longitude)
    data = get_wetland_subregions_in_roi(latitude, longitude, buffer_miles)
    return format_wetland_subregions_summary(data)


@mcp.tool(name="analyze_usace_jurisdiction", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def analyze_usace_jurisdiction_tool(latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0) -> str:
    """Comprehensive USACE jurisdictional analysis for Section 404 compliance.

    Combines regulatory district, wetland region, and subregion data. Use this
    for a one-shot overview; use the individual get_* tools when only one USACE
    dataset is needed.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Analyzing USACE jurisdiction for (%s, %s)", latitude, longitude)
    data = analyze_usace_jurisdiction(latitude, longitude, buffer_miles)
    return format_comprehensive_analysis_summary(data)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
