#!/usr/bin/env python3
"""
MCP Server for U.S. Census Bureau Data

Provides socioeconomic data from the American Community Survey (ACS) for
counties intersecting a Region of Interest (ROI).

Data Source: U.S. Census Bureau American Community Survey 5-Year Estimates

Requires: CENSUS_API_KEY environment variable
Get one at: https://api.census.gov/data/key_signup.html
"""

import logging
import os
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

from src.apis.simplified_census_api import (
    SimplifiedCensusAPI,
    CensusError,
    format_census_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("census-mcp-server")

mcp = FastMCP("census-server")

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
TopCount = Annotated[
    int,
    Field(
        ge=1,
        le=10,
        description="Number of top industries or occupations per county, valid range 1 to 10.",
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


@mcp.tool(name="get_acs_socioeconomic_indicators_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_census_data(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    include_industries: bool = False,
    top_n: TopCount = 2,
) -> str:
    """Query ACS socioeconomic indicators for counties within a region of interest.

    Useful for establishing socioeconomic baseline conditions for NEPA analysis.
    Returns economic indicators (income, poverty, unemployment) and labor statistics
    for each county intersecting the ROI buffer.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
        include_industries: Include top industries/occupations data (default: False)
        top_n: Number of top industries/occupations per county (default: 2)
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying Census data for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)

    # Check for API key
    if not os.getenv("CENSUS_API_KEY"):
        return "Error: CENSUS_API_KEY environment variable not set. Get a free API key at: https://api.census.gov/data/key_signup.html"

    try:
        api = SimplifiedCensusAPI()
    except CensusError as e:
        return f"Error: {str(e)}"

    census_data = api.get_census_data_by_coordinates(
        lat=latitude,
        lon=longitude,
        buffer_miles=buffer_miles,
        include_industries=include_industries,
        top_n=top_n,
    )

    return format_census_summary(census_data)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
