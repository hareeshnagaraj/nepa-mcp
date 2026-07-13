#!/usr/bin/env python3
"""
MCP Server for GBIF (Global Biodiversity Information Facility)

Provides georeferenced species occurrence data with actual observation coordinates.
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

from src.apis.gbif_api import (
    get_gbif_occurrences_in_roi,
    get_gbif_species_by_county_sync,
    format_occurrences_summary,
    format_species_by_county_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gbif-mcp-server")

mcp = FastMCP("gbif-server")

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
MaxRecords = Annotated[
    int,
    Field(
        ge=1,
        le=5000,
        description="Maximum records to retrieve, valid range 1 to 5000.",
    ),
]
MaxRecordsPerCounty = Annotated[
    int,
    Field(
        ge=1,
        le=5000,
        description="Maximum records per county, valid range 1 to 5000.",
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


@mcp.tool(name="get_gbif_species_occurrences_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_species_occurrences_in_roi(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    threatened_only: bool = True,
    min_year: int = 2015,
    max_records: MaxRecords = 1000,
) -> str:
    """Query GBIF for georeferenced threatened & endangered species occurrences.

    Returns actual observation coordinates (lat/lon) unlike IPaC which only provides
    species lists. Ideal for mapping species sightings and analyzing habitat use patterns.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
        threatened_only: Only return threatened/endangered species (default: true)
        min_year: Minimum observation year (default: 2015)
        max_records: Maximum records to retrieve, valid range 1 to 5000 (default: 1000).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Calling GBIF for (%s, %s) at %s mi", latitude, longitude, buffer_miles)

    data = get_gbif_occurrences_in_roi(
        latitude, longitude, buffer_miles, threatened_only=threatened_only, min_year=min_year, max_records=max_records
    )

    return format_occurrences_summary(data, min_year, threatened_only)


@mcp.tool(name="get_gbif_species_list_by_county", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_species_list_by_county(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    threatened_only: bool = True,
    min_year: int = 2015,
    max_records_per_county: MaxRecordsPerCounty = 1000,
) -> str:
    """Query GBIF for threatened & endangered species presence by county.

    Returns species lists aggregated by county within the ROI buffer.
    Appropriate for NEPA/EIS reports where county-level presence is needed.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
        threatened_only: Only return threatened/endangered species (default: true)
        min_year: Minimum observation year (default: 2015)
        max_records_per_county: Maximum records per county, valid range 1 to 5000 (default: 1000).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Calling GBIF for species by county at (%s, %s)", latitude, longitude)
    data = get_gbif_species_by_county_sync(
        latitude,
        longitude,
        buffer_miles,
        threatened_only=threatened_only,
        min_year=min_year,
        max_records_per_county=max_records_per_county,
    )

    return format_species_by_county_summary(data, min_year, threatened_only)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
