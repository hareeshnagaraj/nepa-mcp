"""
GBIF (Global Biodiversity Information Facility) API helper functions.
Provides georeferenced species occurrence data with actual observation coordinates.


Performance optimizations:
- Single query with all IUCN categories (4x fewer API calls)
- Async parallel county queries with semaphore rate limiting (Nx faster for N counties)
"""

from __future__ import annotations

import asyncio
from datetime import date
import logging
import math
import time
import requests
from typing import Dict, List, Optional
from src.apis.counties_api import get_counties_in_roi
from src.core.fips_utils import STATE_FIPS_TO_NAME, STATE_FIPS_TO_ABBR

# Module logger
logger = logging.getLogger(__name__)

# Parallelization settings
# GBIF API has no strict rate limit - tested up to 100 concurrent requests successfully
# Optimal throughput observed at 10-20 concurrent requests
MAX_CONCURRENT_REQUESTS = 15  # Balanced setting for good throughput
GBIF_RATE_LIMIT_SECONDS = 0.05  # Minimal delay (GBIF is very permissive)
MILES_PER_DEGREE_LATITUDE = 69.0

# IUCN Red List category codes for GBIF API
# CR = Critically Endangered, EN = Endangered, VU = Vulnerable, NT = Near Threatened
# NOTE: GBIF API requires multiple params (not comma-separated) for OR logic
IUCN_CATEGORIES_LIST = ["CR", "EN", "VU", "NT"]

# Mapping from IUCN codes to full names (for display)
IUCN_CODE_TO_NAME = {
    "CR": "Critically Endangered",
    "EN": "Endangered",
    "VU": "Vulnerable",
    "NT": "Near Threatened",
}


def _gbif_year_range(min_year: int) -> str:
    """Return a GBIF inclusive year range from min_year through the current year."""
    return f"{min_year},{date.today().year}"


def _gbif_bbox_params(lat: float, lon: float, buffer_miles: float) -> Dict[str, str]:
    """Return GBIF latitude/longitude bounding-box params around a radius in miles."""
    lat_delta = buffer_miles / MILES_PER_DEGREE_LATITUDE
    min_lat = max(-90.0, lat - lat_delta)
    max_lat = min(90.0, lat + lat_delta)

    if min_lat <= -90.0 or max_lat >= 90.0:
        min_lon = -180.0
        max_lon = 180.0
    else:
        lon_delta = buffer_miles / (MILES_PER_DEGREE_LATITUDE * math.cos(math.radians(lat)))
        min_lon = max(-180.0, lon - lon_delta)
        max_lon = min(180.0, lon + lon_delta)

    return {
        "decimalLatitude": f"{min_lat:.6f},{max_lat:.6f}",
        "decimalLongitude": f"{min_lon:.6f},{max_lon:.6f}",
    }


# =============================================================================
# HELPER FUNCTIONS (shared logic to avoid duplication)
# =============================================================================


def _deduplicate_to_species_list(occurrences: List[Dict], include_date_range: bool = True) -> List[Dict]:
    """
    Deduplicate occurrence records to a unique species list.

    Args:
        occurrences: List of occurrence records from GBIF
        include_date_range: If True, track first_seen/last_seen dates

    Returns:
        Sorted list of unique species dictionaries
    """
    species_dict = {}

    for occ in occurrences:
        sci_name = occ.get("scientific_name", "Unknown")
        if not sci_name or sci_name == "Unknown":
            continue

        if sci_name not in species_dict:
            species_dict[sci_name] = {
                "scientific_name": sci_name,
                "common_name": occ.get("common_name", ""),
                "threat_status": occ.get("threat_status", ""),
                "observation_count": 0,
            }
            if include_date_range:
                species_dict[sci_name]["first_seen"] = occ.get("observation_date", "")
                species_dict[sci_name]["last_seen"] = occ.get("observation_date", "")

        species_dict[sci_name]["observation_count"] += 1

        # Update date range if tracking
        if include_date_range:
            obs_date = occ.get("observation_date", "")
            if obs_date:
                current_first = species_dict[sci_name]["first_seen"]
                current_last = species_dict[sci_name]["last_seen"]
                if not current_first or obs_date < current_first:
                    species_dict[sci_name]["first_seen"] = obs_date
                if not current_last or obs_date > current_last:
                    species_dict[sci_name]["last_seen"] = obs_date

    return sorted(species_dict.values(), key=lambda x: (x["threat_status"], x["scientific_name"]))


def _calculate_county_summary(county_results: List[Dict]) -> Dict:
    """
    Calculate summary statistics across all county results.

    Args:
        county_results: List of county dictionaries with species_list

    Returns:
        Summary dictionary with totals and threat status counts
    """
    total_species_count = sum(c.get("total_species", 0) for c in county_results)
    total_observations = sum(c.get("total_observations", 0) for c in county_results)

    # Count unique species across all counties
    all_species = set()
    for county in county_results:
        for species in county.get("species_list", []):
            all_species.add(species.get("scientific_name", ""))

    # Count threat statuses
    threat_status_counts = {}
    for county in county_results:
        for species in county.get("species_list", []):
            status = species.get("threat_status", "Unknown")
            if status:
                threat_status_counts[status] = threat_status_counts.get(status, 0) + 1

    return {
        "total_species_observations": total_species_count,
        "total_observations": total_observations,
        "unique_species_across_all_counties": len(all_species),
        "by_threat_status": threat_status_counts,
    }


def _build_county_result(
    county_name: str,
    state_name: str,
    state_abbr: str,
    fips: str,
    occurrences: List[Dict],
    include_date_range: bool = True,
) -> Dict:
    """
    Build a standardized county result dictionary from occurrences.

    Args:
        county_name: County name (without "County" suffix)
        state_name: Full state name
        state_abbr: State abbreviation
        fips: County FIPS code
        occurrences: List of occurrence records
        include_date_range: If True, include first_seen/last_seen in species

    Returns:
        Standardized county result dictionary
    """
    species_list = _deduplicate_to_species_list(occurrences, include_date_range)

    return {
        "county_name": f"{county_name} County",
        "state": state_name,
        "state_abbr": state_abbr,
        "fips": fips,
        "species_list": species_list,
        "total_species": len(species_list),
        "total_observations": len(occurrences),
    }


# =============================================================================
# MAIN API FUNCTIONS
# =============================================================================


def get_gbif_occurrences_in_roi(
    lat: float,
    lon: float,
    buffer_miles: float,
    threatened_only: bool = True,
    min_year: int = 2015,
    max_records: int = 1000,
) -> Dict:
    """
    Query GBIF for georeferenced species occurrences in a region of interest.

    Unlike IPaC, this returns actual observation coordinates for each species sighting.
    GBIF is queried with a latitude-corrected bounding box around the requested buffer.

    Args:
        lat: Center latitude in decimal degrees (WGS84)
        lon: Center longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles
        threatened_only: If True, only return threatened/endangered species (default: True)
        min_year: Minimum observation year (default: 2015 for recent data)
        max_records: Maximum total records to retrieve (default: 1000)

    Returns:
        Dictionary containing:
        - occurrences: List of observation records with coordinates
        - count: Total number of occurrences
        - summary: Statistics by conservation status
    """

    # Base query parameters for all GBIF requests
    base_params = {
        **_gbif_bbox_params(lat, lon, buffer_miles),
        "country": "US",
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT",
        "year": _gbif_year_range(min_year),
        "limit": 300,  # GBIF max per request
    }

    all_occurrences = []

    if threatened_only:
        # OPTIMIZED: Single query with all IUCN categories (4x fewer API calls than old approach)
        # GBIF API accepts list for OR logic: iucnRedListCategory=CR&iucnRedListCategory=EN&...
        params = base_params.copy()
        params["iucnRedListCategory"] = IUCN_CATEGORIES_LIST
        all_occurrences = _gbif_paginated_query(params, max_records)
    else:
        # Get all species without threat status filter
        all_occurrences = _gbif_paginated_query(base_params, max_records)

    # Calculate summary statistics
    summary = _calculate_summary(all_occurrences)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "occurrences": all_occurrences,
        "count": len(all_occurrences),
        "total_occurrences": len(all_occurrences),
        "unique_species": summary.get("unique_species", 0),
        "summary": summary,
    }


def _gbif_paginated_query(params: Dict, max_records: int = 1000, max_retries: int = 3) -> List[Dict]:
    """
    Handle GBIF pagination to retrieve multiple pages of results.

    Includes retry logic with exponential backoff for rate limiting (429 errors).

    Args:
        params: Query parameters
        max_records: Maximum total records to retrieve
        max_retries: Maximum retry attempts for rate-limited requests

    Returns:
        List of occurrence dictionaries
    """
    all_results = []
    offset = 0
    url = "https://api.gbif.org/v1/occurrence/search"

    while len(all_results) < max_records:
        params["offset"] = offset
        params["limit"] = min(300, max_records - len(all_results))

        # Retry loop with exponential backoff for rate limiting
        for retry in range(max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=30)

                # Handle rate limiting with retry
                if response.status_code == 429:
                    if retry < max_retries:
                        wait_time = (2**retry) + 0.5  # 1.5s, 2.5s, 4.5s
                        logger.warning(f"Rate limited, waiting {wait_time:.1f}s (retry {retry + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"Rate limit exceeded after {max_retries} retries, returning partial results")
                        return all_results

                response.raise_for_status()
                data = response.json()
                break  # Success, exit retry loop

            except requests.exceptions.RequestException as e:
                if retry < max_retries:
                    wait_time = (2**retry) + 0.5
                    logger.warning(f"Request failed, retrying in {wait_time:.1f}s: {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"GBIF API request failed at offset {offset}: {e}")
                    return all_results
        else:
            # All retries exhausted
            return all_results

        # Parse results
        results = data.get("results", [])
        if not results:
            break

        # Parse and format each result
        for record in results:
            occurrence = _parse_gbif_record(record)
            all_results.append(occurrence)

        # Check if we've reached the end
        if data.get("endOfRecords", False):
            break

        offset += len(results)

        # Small delay between pagination requests to avoid rate limiting
        time.sleep(0.1)

    return all_results


def _parse_gbif_record(record: Dict) -> Dict:
    """
    Parse a single GBIF API record into a standardized occurrence dictionary.

    Args:
        record: Raw record from GBIF API response

    Returns:
        Standardized occurrence dictionary
    """
    # Get IUCN status - prefer iucnRedListCategory, fall back to threatStatuses
    iucn_code = record.get("iucnRedListCategory", "")
    threat_status = IUCN_CODE_TO_NAME.get(iucn_code, iucn_code)
    if not threat_status:
        # Fallback to threatStatuses array if iucnRedListCategory not set
        threat_statuses = record.get("threatStatuses", [])
        threat_status = ",".join(threat_statuses) if threat_statuses else ""

    return {
        "gbif_id": record.get("key"),
        "scientific_name": record.get("scientificName", "Unknown"),
        "common_name": record.get("vernacularName", ""),
        "latitude": record.get("decimalLatitude"),
        "longitude": record.get("decimalLongitude"),
        "observation_date": record.get("eventDate", "").split("T")[0] if record.get("eventDate") else "",
        "year": record.get("year"),
        "month": record.get("month"),
        "threat_status": threat_status,
        "state_province": record.get("stateProvince", ""),
        "county": record.get("county", ""),
    }


def _calculate_summary(occurrences: List[Dict]) -> Dict:
    """
    Calculate summary statistics for the occurrences.

    Args:
        occurrences: List of occurrence records

    Returns:
        Summary statistics dictionary
    """
    if not occurrences:
        return {}

    # Count by threat status
    status_counts = {}
    for occ in occurrences:
        status = occ.get("threat_status", "Unknown")
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1

    # Count unique species
    unique_species = set()
    for occ in occurrences:
        sci_name = occ.get("scientific_name")
        if sci_name:
            unique_species.add(sci_name)

    return {
        "total_occurrences": len(occurrences),
        "unique_species": len(unique_species),
        "by_threat_status": status_counts,
    }


def _empty_county_result(lat: float, lon: float, buffer_miles: float) -> Dict:
    """Return an empty result structure for when no counties are found."""
    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "counties": [],
        "total_counties": 0,
        "total_unique_species": 0,
        "summary": {},
    }


def _query_gbif_by_county(
    county_name: str, state_name: str, threatened_only: bool = True, min_year: int = 2015, max_records: int = 1000
) -> List[Dict]:
    """
    Query GBIF API using county and state filters.

    Args:
        county_name: County name (without "County" suffix, e.g., "Los Angeles")
        state_name: Full state name (e.g., "California")
        threatened_only: Filter by threat status
        min_year: Minimum observation year
        max_records: Maximum records to retrieve

    Returns:
        List of occurrence records
    """
    base_params = {
        "county": county_name,
        "stateProvince": state_name,
        "country": "US",
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT",
        "year": _gbif_year_range(min_year),
        "limit": 300,
    }

    all_occurrences = []

    if threatened_only:
        # OPTIMIZED: Single query with all IUCN categories (4x fewer API calls)
        params = base_params.copy()
        params["iucnRedListCategory"] = IUCN_CATEGORIES_LIST
        all_occurrences = _gbif_paginated_query(params, max_records)
    else:
        all_occurrences = _gbif_paginated_query(base_params, max_records)

    return all_occurrences


# =============================================================================
# ASYNC PARALLEL IMPLEMENTATION (with semaphore rate limiting)
# =============================================================================


async def _query_county_async(
    county: Dict,
    semaphore: asyncio.Semaphore,
    threatened_only: bool = True,
    min_year: int = 2015,
    max_records: int = 1000,
) -> Optional[Dict]:
    """
    Async wrapper to query GBIF for a single county with semaphore rate limiting.

    Args:
        county: County dictionary with 'basename', 'state', 'fips' keys
        semaphore: Asyncio semaphore for rate limiting
        threatened_only: Filter by threat status
        min_year: Minimum observation year
        max_records: Maximum records to retrieve

    Returns:
        Dictionary with county info and species data, or None if invalid county
    """
    async with semaphore:
        county_name = county.get("basename", "").strip()
        state_fips = county.get("state", "")
        state_name = STATE_FIPS_TO_NAME.get(state_fips, "")
        state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, "")

        if not county_name or not state_name:
            return None

        logger.info(f"  Querying {county_name} County, {state_abbr}...")

        # Run sync query in thread pool to avoid blocking event loop
        occurrences = await asyncio.to_thread(
            _query_gbif_by_county,
            county_name=county_name,
            state_name=state_name,
            threatened_only=threatened_only,
            min_year=min_year,
            max_records=max_records,
        )

        # Rate limiting delay
        await asyncio.sleep(GBIF_RATE_LIMIT_SECONDS)

        # Use helper to build result (handles empty occurrences too)
        result = _build_county_result(
            county_name=county_name,
            state_name=state_name,
            state_abbr=state_abbr,
            fips=county.get("fips", ""),
            occurrences=occurrences or [],
        )

        logger.info(f"    Found {result['total_species']} unique species ({result['total_observations']} observations)")
        return result


async def get_gbif_species_by_county_async(
    lat: float,
    lon: float,
    buffer_miles: float = 25.0,
    threatened_only: bool = True,
    min_year: int = 2015,
    max_records_per_county: int = 1000,
) -> Dict:
    """
    ASYNC version: Query GBIF for species presence by county with parallel requests.

    Uses semaphore to limit concurrent API calls and avoid overwhelming GBIF.
    Significantly faster than sequential version for multi-county ROIs.

    Performance improvement:
    - Sequential (old): N counties x 1 query each = N sequential calls
    - Parallel (new): N counties queried concurrently (max 15 at a time)
    - Speedup: ~5-7x for typical ROIs

    Args:
        lat: Center latitude in decimal degrees (WGS84)
        lon: Center longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default: 25)
        threatened_only: If True, only return threatened/endangered species (default: True)
        min_year: Minimum observation year (default: 2015 for recent data)
        max_records_per_county: Maximum records to retrieve per county (default: 1000)

    Returns:
        Dictionary containing county species data (same format as sync version)
    """
    logger.info(f"Identifying counties in ROI ({lat}, {lon}) with {buffer_miles} mile buffer")
    counties_data = get_counties_in_roi(lat, lon, buffer_miles)

    if not counties_data.get("counties"):
        return _empty_county_result(lat, lon, buffer_miles)

    counties = counties_data["counties"]
    logger.info(f"Found {len(counties)} counties. Querying GBIF in parallel (max {MAX_CONCURRENT_REQUESTS} concurrent)")

    # Query all counties in parallel with semaphore rate limiting
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    tasks = [
        _query_county_async(
            county=county,
            semaphore=semaphore,
            threatened_only=threatened_only,
            min_year=min_year,
            max_records=max_records_per_county,
        )
        for county in counties
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    county_results = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"County query failed: {result}")
            continue
        if result is not None:
            county_results.append(result)

    # Use helper to calculate summary
    summary = _calculate_county_summary(county_results)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "counties": county_results,
        "total_counties": len(county_results),
        "total_unique_species": summary["unique_species_across_all_counties"],
        "summary": summary,
    }


def get_gbif_species_by_county_sync(
    lat: float,
    lon: float,
    buffer_miles: float = 25.0,
    threatened_only: bool = True,
    min_year: int = 2015,
    max_records_per_county: int = 1000,
) -> Dict:
    """
    Query GBIF for species presence by county with parallel requests.

    Sync wrapper for get_gbif_species_by_county_async(). Use this from synchronous
    code (CLI, scripts). For async contexts (MCP servers), use the async version directly.

    Args:
        lat: Center latitude in decimal degrees (WGS84)
        lon: Center longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default: 25)
        threatened_only: If True, only return threatened/endangered species (default: True)
        min_year: Minimum observation year (default: 2015 for recent data)
        max_records_per_county: Maximum records to retrieve per county (default: 1000)

    Returns:
        Dictionary containing county species data
    """
    return asyncio.run(
        get_gbif_species_by_county_async(
            lat=lat,
            lon=lon,
            buffer_miles=buffer_miles,
            threatened_only=threatened_only,
            min_year=min_year,
            max_records_per_county=max_records_per_county,
        )
    )


# =============================================================================
# Formatting helpers
# =============================================================================


def format_occurrences_summary(gbif_data: Dict, min_year: int, threatened_only: bool) -> str:
    """
    Format GBIF occurrence data as a markdown summary.

    Args:
        gbif_data: Data from get_gbif_occurrences_in_roi()
        min_year: Minimum year filter used in query
        threatened_only: Whether query was filtered to threatened species

    Returns:
        Formatted markdown string
    """
    center = gbif_data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = gbif_data.get("buffer_miles", 0)
    summary = gbif_data.get("summary", {})
    occurrences = gbif_data.get("occurrences", [])

    lines = [
        "GBIF Georeferenced Species Occurrences",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Date Range: {min_year}-present",
        f"Filter: {'Threatened/Endangered only' if threatened_only else 'All species'}",
        "",
        f"Total Occurrences: {summary.get('total_occurrences', 0)}",
        f"Unique Species: {summary.get('unique_species', 0)}",
        "",
    ]

    by_status = summary.get("by_threat_status", {})
    if by_status:
        lines.append("By Conservation Status:")
        for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
            lines.append(f"  - {status}: {count}")
        lines.append("")

    if occurrences:
        species_counts = {}
        for occ in occurrences:
            sci_name = occ.get("scientific_name", "Unknown")
            common = occ.get("common_name", "")
            key = (sci_name, common)
            species_counts[key] = species_counts.get(key, 0) + 1

        top_species = sorted(species_counts.items(), key=lambda x: -x[1])[:10]

        lines.append("Most Frequently Observed Species:")
        for (sci_name, common), count in top_species:
            display_name = f"{common} ({sci_name})" if common else sci_name
            lines.append(f"  - {display_name}: {count} occurrences")
        lines.append("")

    lines.append("Data Source: GBIF (Global Biodiversity Information Facility)")
    lines.append("Note: These are actual georeferenced observation locations, not estimated ranges.")

    return "\n".join(lines)


def format_species_by_county_summary(county_data: Dict, min_year: int, threatened_only: bool) -> str:
    """
    Format GBIF species by county data as a markdown summary.

    Args:
        county_data: Data from get_gbif_species_by_county_async()
        min_year: Minimum year filter used in query
        threatened_only: Whether query was filtered to threatened species

    Returns:
        Formatted markdown string
    """
    center = county_data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = county_data.get("buffer_miles", 0)
    summary = county_data.get("summary", {})
    counties = county_data.get("counties", [])

    lines = [
        "GBIF Species Presence by County",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Date Range: {min_year}-present",
        f"Filter: {'Threatened/Endangered only' if threatened_only else 'All species'}",
        "",
        f"Total Counties: {county_data.get('total_counties', 0)}",
        f"Total Unique Species (across all counties): {county_data.get('total_unique_species', 0)}",
        f"Total Species-County Records: {summary.get('total_species_observations', 0)}",
        f"Total Observations: {summary.get('total_observations', 0)}",
        "",
    ]

    by_status = summary.get("by_threat_status", {})
    if by_status:
        lines.append("Species-County Records by Conservation Status:")
        for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
            lines.append(f"  - {status}: {count}")
        lines.append("")

    if counties:
        lines.append("Species by County:")
        for county in counties:
            county_name = county.get("county_name", "Unknown")
            state_abbr = county.get("state_abbr", "")
            species_count = county.get("total_species", 0)
            obs_count = county.get("total_observations", 0)

            lines.append(f"\n  {county_name}, {state_abbr}:")
            lines.append(f"    - Species: {species_count}")
            lines.append(f"    - Observations: {obs_count}")

            species_list = county.get("species_list", [])[:5]
            if species_list:
                lines.append("    - Top Species:")
                for species in species_list:
                    sci_name = species.get("scientific_name", "Unknown")
                    common = species.get("common_name", "")
                    obs = species.get("observation_count", 0)
                    status = species.get("threat_status", "")

                    display_name = f"{common} ({sci_name})" if common else sci_name
                    lines.append(f"      * {display_name}: {obs} obs, {status}")

    lines.append("")
    lines.append("Data Source: GBIF (Global Biodiversity Information Facility)")
    lines.append("Note: This shows species presence by county without individual observation coordinates.")

    return "\n".join(lines)
