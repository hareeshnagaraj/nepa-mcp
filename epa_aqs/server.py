#!/usr/bin/env python3
"""
MCP Server for EPA Air Quality System (AQS) Data

Provides tools for querying EPA's Air Quality System API for criteria pollutant
monitoring data. Essential for NEPA/EIS air quality baseline assessments.

API Documentation: https://aqs.epa.gov/aqsweb/documents/data_api.html
Register for API access: https://aqs.epa.gov/data/api/signup

Requires: EPA_AQS_EMAIL and EPA_AQS_API_KEY environment variables
"""

import logging
import sys
from pathlib import Path
from typing import Annotated
from datetime import datetime

# Add the server directory to path for local imports
SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pydantic import Field

from fastmcp import FastMCP

from src.apis.aqs_api import (
    calculate_bounding_box,
    get_monitors_by_box,
    get_annual_data_by_box,
    assess_naaqs_compliance,
    get_aqs_credentials,
    format_monitors_summary,
    format_air_quality_summary,
)
from src.apis.aqs_constants import get_criteria_pollutant_codes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("epa-aqs-mcp-server")

mcp = FastMCP("epa-aqs-server")

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


DEFAULT_POLLUTANTS = ["PM2.5", "PM10", "Ozone", "NO2", "SO2", "CO"]
AQS_TOOL_TIMEOUT_SECONDS = 240.0


def _check_credentials() -> tuple:
    """Check if AQS credentials are configured."""
    try:
        get_aqs_credentials()
        return True, ""
    except ValueError as e:
        return False, str(e)


@mcp.tool(
    name="get_epa_aqs_air_quality_monitors",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=AQS_TOOL_TIMEOUT_SECONDS,
)
async def get_air_quality_monitors(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    year: int | None = None,
    pollutants: list[str] | None = None,
) -> str:
    """Identify EPA air quality monitoring stations within a region of interest.

    Returns monitor locations, operational dates, and measured pollutants.
    Use this to identify available air quality data sources for NEPA baseline assessment.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles around the point, valid range 0.1 to 100.0 (default: 25).
        year: Year to query for active monitors (default: current year)
        pollutants: List of pollutants to query (PM2.5, PM10, Ozone, NO2, SO2, CO). Default: all
    """
    # Check credentials
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    has_creds, error_msg = _check_credentials()
    if not has_creds:
        return f"Error: EPA AQS API credentials not configured. {error_msg}"

    if year is None:
        year = datetime.now().year
    if pollutants is None:
        pollutants = DEFAULT_POLLUTANTS

    logger.info(
        f"Finding air quality monitors at ({latitude}, {longitude}) within {buffer_miles} miles for year {year}"
    )

    bbox = calculate_bounding_box(latitude, longitude, buffer_miles)

    pollutant_codes = get_criteria_pollutant_codes()
    param_codes = [pollutant_codes[p] for p in pollutants if p in pollutant_codes]

    if not param_codes:
        return f"Error: No valid pollutants specified. Available: {list(pollutant_codes.keys())}"

    begin_date = f"{year}0101"
    end_date = f"{year}1231"

    monitors = await get_monitors_by_box(bbox, begin_date, end_date, param_codes)

    return format_monitors_summary(monitors, latitude, longitude, buffer_miles)


@mcp.tool(
    name="get_epa_aqs_annual_air_quality",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=AQS_TOOL_TIMEOUT_SECONDS,
)
async def get_annual_air_quality(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    begin_year: int | None = None,
    end_year: int | None = None,
    pollutants: list[str] | None = None,
) -> str:
    """Get annual air quality statistics for criteria pollutants in a region.

    Returns annual means, maximum values, and screening comparisons against
    selected NAAQS values. Use this when annual AQS statistics are needed without
    also retrieving monitor metadata.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles around the point, valid range 0.1 to 100.0 (default: 25).
        begin_year: First year to query (default: last year)
        end_year: Last year to query (default: last year)
        pollutants: List of pollutants to query. Default: all criteria pollutants
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    has_creds, error_msg = _check_credentials()
    if not has_creds:
        return f"Error: EPA AQS API credentials not configured. {error_msg}"

    current_year = datetime.now().year
    if begin_year is None:
        begin_year = current_year - 1
    if end_year is None:
        end_year = current_year - 1
    if pollutants is None:
        pollutants = DEFAULT_POLLUTANTS

    logger.info(
        f"Getting annual air quality data at ({latitude}, {longitude}) within {buffer_miles} miles for {begin_year}-{end_year}"
    )

    bbox = calculate_bounding_box(latitude, longitude, buffer_miles)

    pollutant_codes = get_criteria_pollutant_codes()
    param_codes = [pollutant_codes[p] for p in pollutants if p in pollutant_codes]

    if not param_codes:
        return f"Error: No valid pollutants specified. Available: {list(pollutant_codes.keys())}"

    annual_data = await get_annual_data_by_box(bbox, begin_year, end_year, param_codes)

    compliance = assess_naaqs_compliance(annual_data)

    return format_air_quality_summary(annual_data, compliance, latitude, longitude, buffer_miles, begin_year, end_year)


@mcp.tool(
    name="analyze_epa_aqs_air_quality_baseline",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=AQS_TOOL_TIMEOUT_SECONDS,
)
async def analyze_air_quality_baseline(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    begin_year: int | None = None,
    end_year: int | None = None,
    pollutants: list[str] | None = None,
) -> str:
    """Analyze EPA AQS air quality baseline data for NEPA screening.

    One-shot overview that combines monitor discovery with annual AQS statistics,
    then compares observed annual metrics to selected NAAQS values for screening
    context. Use the individual get_* tools when only one dataset is needed.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles around the point, valid range 0.1 to 100.0 (default: 25).
        begin_year: First year for baseline period (default: last year)
        end_year: Last year for baseline period (default: last year)
        pollutants: List of pollutants to analyze. Default: all criteria pollutants
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    has_creds, error_msg = _check_credentials()
    if not has_creds:
        return f"Error: EPA AQS API credentials not configured. {error_msg}"

    current_year = datetime.now().year
    if begin_year is None:
        begin_year = current_year - 1
    if end_year is None:
        end_year = current_year - 1
    if pollutants is None:
        pollutants = DEFAULT_POLLUTANTS

    logger.info(f"Performing comprehensive air quality baseline analysis at ({latitude}, {longitude})")

    bbox = calculate_bounding_box(latitude, longitude, buffer_miles)

    pollutant_codes = get_criteria_pollutant_codes()
    param_codes = [pollutant_codes[p] for p in pollutants if p in pollutant_codes]

    if not param_codes:
        return f"Error: No valid pollutants specified. Available: {list(pollutant_codes.keys())}"

    # Step 1: Get monitors
    logger.info("Step 1: Getting monitors...")
    monitors = await get_monitors_by_box(bbox, f"{end_year}0101", f"{end_year}1231", param_codes)

    # Step 2: Get annual data
    logger.info("Step 2: Getting annual data...")
    annual_data = await get_annual_data_by_box(bbox, begin_year, end_year, param_codes)

    # Step 3: NAAQS screening comparison
    logger.info("Step 3: Comparing annual data to NAAQS screening values...")
    compliance = assess_naaqs_compliance(annual_data)

    # Combine monitors summary and air quality summary
    monitors_summary = format_monitors_summary(monitors, latitude, longitude, buffer_miles)
    air_quality_summary = format_air_quality_summary(
        annual_data, compliance, latitude, longitude, buffer_miles, begin_year, end_year
    )

    # Return combined comprehensive report
    return f"""Comprehensive Air Quality Baseline Analysis

{monitors_summary}

---

{air_quality_summary}"""


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", stateless_http=True)
