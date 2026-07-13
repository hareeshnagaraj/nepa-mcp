"""
FEMA National Flood Hazard Layer (NFHL) API Integration.

Pure data access layer for FEMA flood zone, levee, and water area data.
This module handles only API queries; the MCP server returns formatted results inline.

API Documentation: https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer
"""

from __future__ import annotations

import json
import logging
import requests
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# FEMA NFHL MapServer base URL
BASE_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
MAX_FEATURES_PER_QUERY = 10000

# Layer IDs for different data types
LAYERS = {
    "flood_zones": 28,
    "flood_boundaries": 27,
    "firm_panels": 3,
    "levees": 23,
    "structures": 24,
    "bfe": 16,  # Base Flood Elevation
    "water_areas": 32,
    "political_jurisdictions": 22,
}

# Flood zone classifications
FLOOD_ZONE_INFO = {
    "A": "Special Flood Hazard Area (SFHA) - 100-year floodplain, no BFE determined",
    "AE": "SFHA - 100-year floodplain with Base Flood Elevations",
    "AH": "SFHA - Shallow flooding (1-3 ft) with average depths",
    "AO": "SFHA - Sheet flow on sloping terrain",
    "AR": "SFHA - Flood risk due to levee restoration/improvement",
    "A99": "SFHA - To be protected by federal flood protection system under construction",
    "V": "Coastal SFHA with velocity hazard (wave action)",
    "VE": "Coastal SFHA with velocity hazard and BFE",
    "X": "Moderate to low flood risk (500-year floodplain or protected by levee)",
    "D": "Undetermined flood hazard - possible but undetermined risk",
}

# =============================================================================
# Internal Helpers
# =============================================================================


@dataclass(frozen=True)
class NFHLLayerQueryResult:
    """Paginated NFHL layer query result."""

    records: List[Dict[str, Any]]
    warnings: List[str]
    truncated: bool = False


def _build_query_result(
    lat: float,
    lon: float,
    radius_miles: float,
    records: List[Dict[str, Any]],
    data_key: str,
    total_key: str,
    summary_fn: Optional[Callable[[List[Dict[str, Any]]], Dict[str, Any]]] = None,
    warnings: Optional[List[str]] = None,
    truncated: bool = False,
) -> Dict[str, Any]:
    """Build standardized query result dict."""
    result = {
        "center": {"latitude": lat, "longitude": lon},
        "radius_miles": radius_miles,
        total_key: len(records),
        data_key: records,
        "warnings": warnings or [],
        "truncated": truncated,
    }
    if summary_fn:
        result["summary"] = summary_fn(records)
    return result


def _query_nfhl_layer_result(
    layer_id: int,
    lat: float,
    lon: float,
    radius_miles: float = 100.0,
    out_fields: str = "*",
    return_geometry: bool = False,
    max_features: int = MAX_FEATURES_PER_QUERY,
) -> NFHLLayerQueryResult:
    """
    Query NFHL layer within radius of a point with pagination support.

    Args:
        layer_id: NFHL MapServer layer ID
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        radius_miles: Search radius in miles (default: 100)
        out_fields: Fields to return (default: all)
        return_geometry: Whether to include geometry in response
        max_features: Maximum records to collect before truncating

    Returns:
        Paginated layer query result with feature attributes and warnings.
    """
    query_url = f"{BASE_URL}/{layer_id}/query"
    radius_meters = radius_miles * 1609.34

    all_features = []
    warnings = []
    truncated = False
    offset = 0
    max_records = 2000

    while True:
        remaining = max_features - len(all_features)
        if remaining <= 0:
            truncated = True
            warning = f"FEMA NFHL layer {layer_id} reached max_features={max_features}; results are partial."
            warnings.append(warning)
            logger.warning(warning)
            break
        page_size = min(max_records, remaining)

        params = {
            "f": "json",
            "geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "distance": radius_meters,
            "units": "esriSRUnit_Meter",
            "outFields": out_fields,
            "returnGeometry": return_geometry,
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }

        try:
            response = requests.get(query_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(f"FEMA API error: {data['error'].get('message', 'Unknown error')}")

            features = data.get("features", [])
            if not isinstance(features, list):
                raise RuntimeError("FEMA API returned malformed features")
            exceeded = bool(data.get("exceededTransferLimit", False))

            if not features:
                if exceeded:
                    truncated = True
                    warning = f"FEMA NFHL layer {layer_id} reported more records but returned an empty page."
                    warnings.append(warning)
                    logger.warning(warning)
                break

            all_features.extend(features[:remaining])

            if len(all_features) >= max_features:
                if exceeded or len(features) > remaining:
                    truncated = True
                    warning = f"FEMA NFHL layer {layer_id} reached max_features={max_features}; results are partial."
                    warnings.append(warning)
                    logger.warning(warning)
                break

            if not exceeded:
                break

            offset += page_size
            logger.info(f"Fetched {len(all_features)} features so far, continuing pagination...")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to query FEMA NFHL API: {e}") from e

    # Extract attributes from features
    records = [f.get("attributes", {}) for f in all_features]
    return NFHLLayerQueryResult(records=records, warnings=warnings, truncated=truncated)


def query_nfhl_layer(
    layer_id: int,
    lat: float,
    lon: float,
    radius_miles: float = 100.0,
    out_fields: str = "*",
    return_geometry: bool = False,
    max_features: int = MAX_FEATURES_PER_QUERY,
) -> List[Dict[str, Any]]:
    """
    Query NFHL layer within radius of a point with pagination support.

    Args:
        layer_id: NFHL MapServer layer ID
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        radius_miles: Search radius in miles (default: 100)
        out_fields: Fields to return (default: all)
        return_geometry: Whether to include geometry in response
        max_features: Maximum records to collect before truncating

    Returns:
        List of feature attribute dictionaries
    """
    result = _query_nfhl_layer_result(layer_id, lat, lon, radius_miles, out_fields, return_geometry, max_features)
    return result.records


def _compute_flood_zone_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute flood zone statistics from records."""
    zone_counts: Dict[str, int] = {}
    sfha_count = 0

    for record in records:
        zone = record.get("FLD_ZONE", "Unknown")
        zone_counts[zone] = zone_counts.get(zone, 0) + 1
        if record.get("SFHA_TF") == "T":
            sfha_count += 1

    sfha_percentage = (sfha_count / len(records) * 100) if records else 0

    return {
        "zone_counts": zone_counts,
        "sfha_count": sfha_count,
        "sfha_percentage": round(sfha_percentage, 1),
    }


def get_flood_zones(lat: float, lon: float, radius_miles: float = 100.0) -> Dict[str, Any]:
    """
    Query FEMA flood hazard zones within a radius of a location.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        radius_miles: Search radius in miles (default: 100)

    Returns:
        Dictionary containing:
        - center: Query center point
        - radius_miles: Search radius
        - total_zones: Number of flood zones found
        - zones: List of flood zone records
        - summary: Zone statistics
    """
    result = _query_nfhl_layer_result(LAYERS["flood_zones"], lat, lon, radius_miles)
    return _build_query_result(
        lat,
        lon,
        radius_miles,
        result.records,
        data_key="zones",
        total_key="total_zones",
        summary_fn=_compute_flood_zone_summary,
        warnings=result.warnings,
        truncated=result.truncated,
    )


def get_levees(lat: float, lon: float, radius_miles: float = 100.0) -> Dict[str, Any]:
    """
    Query FEMA levee locations within a radius of a location.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        radius_miles: Search radius in miles (default: 100)

    Returns:
        Dictionary containing:
        - center: Query center point
        - radius_miles: Search radius
        - total_levees: Number of levees found
        - levees: List of levee records
    """
    result = _query_nfhl_layer_result(LAYERS["levees"], lat, lon, radius_miles)
    return _build_query_result(
        lat,
        lon,
        radius_miles,
        result.records,
        data_key="levees",
        total_key="total_levees",
        warnings=result.warnings,
        truncated=result.truncated,
    )


def get_water_areas(lat: float, lon: float, radius_miles: float = 100.0) -> Dict[str, Any]:
    """
    Query FEMA water areas (rivers, lakes, etc.) within a radius.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        radius_miles: Search radius in miles (default: 100)

    Returns:
        Dictionary containing:
        - center: Query center point
        - radius_miles: Search radius
        - total_water_areas: Number of water areas found
        - water_areas: List of water area records
    """
    result = _query_nfhl_layer_result(LAYERS["water_areas"], lat, lon, radius_miles)
    return _build_query_result(
        lat,
        lon,
        radius_miles,
        result.records,
        data_key="water_areas",
        total_key="total_water_areas",
        warnings=result.warnings,
        truncated=result.truncated,
    )


def analyze_flood_risk(lat: float, lon: float, radius_miles: float = 100.0) -> Dict[str, Any]:
    """
    FEMA NFHL flood-hazard screening for a location.

    Retrieves flood zones, levee systems, and water areas for screening context.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        radius_miles: Search radius in miles (default: 100)

    Returns:
        Dictionary containing:
        - center: Query center point
        - radius_miles: Search radius
        - flood_zones: Flood zone data and statistics
        - levees: Levee data
        - water_areas: Water area data
        - hazard_screening: Relative screening indicator based on intersecting NFHL records
    """
    # Gather all data
    flood_data = get_flood_zones(lat, lon, radius_miles)
    levee_data = get_levees(lat, lon, radius_miles)
    water_data = get_water_areas(lat, lon, radius_miles)

    # Compute a coarse screening indicator from intersecting SFHA records.
    sfha_pct = flood_data["summary"]["sfha_percentage"]

    if sfha_pct >= 50:
        hazard_level = "HIGH"
        hazard_description = "Significant portion of returned NFHL records are within Special Flood Hazard Areas"
    elif sfha_pct >= 20:
        hazard_level = "MODERATE"
        hazard_description = "Moderate share of returned NFHL records are within Special Flood Hazard Areas"
    elif sfha_pct > 0:
        hazard_level = "LOW"
        hazard_description = "Limited returned NFHL records are within Special Flood Hazard Areas"
    else:
        hazard_level = "MINIMAL"
        hazard_description = "No Special Flood Hazard Area records identified in the query response"

    return {
        "center": {"latitude": lat, "longitude": lon},
        "radius_miles": radius_miles,
        "flood_zones": flood_data,
        "levees": levee_data,
        "water_areas": water_data,
        "hazard_screening": {
            "hazard_level": hazard_level,
            "hazard_description": hazard_description,
            "sfha_percentage": sfha_pct,
            "has_levee_protection": levee_data["total_levees"] > 0,
        },
    }


# =============================================================================
# Summary Formatting Functions
# =============================================================================


def _format_summary(
    title: str,
    data: Dict[str, Any],
    total_key: str,
    extra_lines_fn: Optional[Callable[[Dict[str, Any]], List[str]]] = None,
) -> str:
    """Generic markdown summary formatter."""
    lat = data["center"]["latitude"]
    lon = data["center"]["longitude"]
    radius = data["radius_miles"]
    total = data[total_key]

    lines = [
        title,
        "",
        f"Location: ({lat}, {lon})",
        f"Radius: {radius} miles",
        f"Total: {total}",
    ]

    for warning in data.get("warnings", []):
        lines.append(f"Warning: {warning}")

    if extra_lines_fn:
        lines.extend(extra_lines_fn(data))

    return "\n".join(lines)


def _flood_zones_extra_lines(data: Dict[str, Any]) -> List[str]:
    """Generate extra lines for flood zone summary."""
    summary = data["summary"]
    lines = [
        f"SFHA Zones: {summary['sfha_count']} ({summary['sfha_percentage']}%)",
        "",
        "Flood Zone Distribution:",
    ]
    for zone, count in sorted(summary["zone_counts"].items(), key=lambda x: -x[1]):
        zone_desc = FLOOD_ZONE_INFO.get(zone, "")
        line = f"  {zone}: {count} zones"
        if zone_desc:
            line += f" - {zone_desc}"
        lines.append(line)
    return lines


def format_flood_zones_summary(flood_data: Dict[str, Any]) -> str:
    """Format flood zone data as a markdown summary."""
    return _format_summary("FEMA Flood Zones Analysis", flood_data, "total_zones", _flood_zones_extra_lines)


def format_levees_summary(levee_data: Dict[str, Any]) -> str:
    """Format levee data as a markdown summary."""
    return _format_summary("FEMA Levees", levee_data, "total_levees")


def format_water_areas_summary(water_data: Dict[str, Any]) -> str:
    """Format water area data as a markdown summary."""
    return _format_summary("FEMA Water Areas", water_data, "total_water_areas")


def format_flood_risk_summary(risk_data: Dict[str, Any]) -> str:
    """Format FEMA NFHL flood-hazard screening as a markdown summary."""
    lat = risk_data["center"]["latitude"]
    lon = risk_data["center"]["longitude"]
    radius = risk_data["radius_miles"]
    assessment = risk_data["hazard_screening"]
    flood_summary = risk_data["flood_zones"]["summary"]

    lines = [
        "FEMA NFHL Flood-Hazard Screening",
        "",
        f"Location: ({lat}, {lon})",
        f"Radius: {radius} miles",
        "",
        "---",
        "",
        "Screening Indicator",
        "",
        f"Hazard Level: {assessment['hazard_level']}",
        f"Description: {assessment['hazard_description']}",
        f"SFHA Coverage: {assessment['sfha_percentage']}%",
        f"Levee Protection: {'Yes' if assessment['has_levee_protection'] else 'No'}",
    ]

    warnings = []
    for section in ("flood_zones", "levees", "water_areas"):
        warnings.extend(risk_data[section].get("warnings", []))
    for warning in warnings:
        lines.append(f"Warning: {warning}")

    lines.extend(
        [
            "",
            "---",
            "",
            "Flood Hazard Zones",
            "",
            f"Total Zones: {risk_data['flood_zones']['total_zones']}",
            f"SFHA Zones: {flood_summary['sfha_count']} ({flood_summary['sfha_percentage']}%)",
            "",
            "Zone Distribution:",
        ]
    )

    for zone, count in sorted(flood_summary["zone_counts"].items(), key=lambda x: -x[1]):
        lines.append(f"  {zone}: {count} zones")

    lines.extend(
        [
            "",
            "---",
            "",
            "Levee Systems",
            "",
            f"Total Levees: {risk_data['levees']['total_levees']}",
            "",
            "---",
            "",
            "Water Areas",
            "",
            f"Total Water Areas: {risk_data['water_areas']['total_water_areas']}",
            "",
            "Note: This is a screening summary from FEMA NFHL records, not a site-specific flood study or engineering determination.",
        ]
    )

    return "\n".join(lines)
