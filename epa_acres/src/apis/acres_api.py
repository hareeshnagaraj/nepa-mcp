"""
EPA ACRES (Assessment, Cleanup and Redevelopment Exchange System) Brownfields utilities.

This module queries the EPA Envirofacts facility-points ArcGIS MapServer to
identify Brownfields properties reported to ACRES within a Region of Interest.
ACRES captures grantee-reported data from EPA Brownfields grant programs, so it
is not a complete inventory of brownfields or contaminated sites, and a record
is not a determination that land is available or suitable for development.

Data source: EPA Envirofacts Brownfields ArcGIS layer
  https://geopub.epa.gov/ArcGIS/rest/services/EMEF/efpoints/MapServer/5
"""

from __future__ import annotations

import logging
from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import validate_coordinates
from src.core.constants import ACRES_BROWNFIELDS_LAYER_ID, ACRES_SERVICE_URL

logger = logging.getLogger(__name__)

# Fields to request from the ACRES Brownfields ArcGIS layer
_OUT_FIELDS = (
    "registry_id,primary_name,location_address,city_name,county_name,state_code,"
    "epa_region,postal_code,latitude,longitude,pgm_sys_id,facility_url"
)

# Cap the per-property detail listing so dense metro ROIs stay readable.
MAX_LISTED_PROPERTIES = 100


def get_epa_acres_properties_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return ACRES Brownfields property records intersecting the ROI.

    Queries the Brownfields layer of the EPA Envirofacts facility-points
    MapServer. Each record is an identifiable property reported to ACRES through
    EPA Brownfields grant programs, with its FRS registry ID, ACRES property ID,
    and EPA Cleanups in my Community source URL.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with:
            - center: {latitude, longitude}
            - buffer_miles: float
            - total: int
            - properties: list of property dicts
            - warnings: list of upstream warnings
            - truncated: bool (upstream feature cap reached; results are partial)
            - data_unavailable: bool (only present when buffering or querying failed)
            - error: str (only present when buffering or querying failed)
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)

    base = {"center": {"latitude": lat, "longitude": lon}, "buffer_miles": buffer_miles}

    try:
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    except Exception as e:
        logger.error("ArcGIS buffer creation failed: %s", e)
        return {
            **base,
            "total": 0,
            "properties": [],
            "warnings": [],
            "truncated": False,
            "data_unavailable": True,
            "error": str(e),
        }

    try:
        result = ArcGISService.query_features(
            ACRES_SERVICE_URL,
            ACRES_BROWNFIELDS_LAYER_ID,
            buffer_geom,
            out_fields=_OUT_FIELDS,
            timeout=30,
            service_name="EPA ACRES Brownfields layer",
        )
    except Exception as e:
        logger.error("EPA ACRES Brownfields layer query failed: %s", e)
        # A failed upstream query is NOT a valid no-hit screen — flag it
        # explicitly so a consumer that ignores warnings cannot mistake an
        # outage for "no Brownfields properties found".
        return {
            **base,
            "total": 0,
            "properties": [],
            "warnings": ["EPA ACRES Brownfields layer query failed; results are unavailable, not a no-hit finding."],
            "truncated": False,
            "data_unavailable": True,
            "error": f"ACRES data unavailable: {e}",
        }

    properties = []
    # `or []` guards against a query result whose features are null rather than
    # an empty list, so a null-features response degrades gracefully instead of
    # raising TypeError.
    for feature in result.features or []:
        attrs = feature.get("attributes", {})
        properties.append(
            {
                "name": attrs.get("primary_name") or "Unknown",
                "address": attrs.get("location_address") or "",
                "city": attrs.get("city_name") or "",
                "county": attrs.get("county_name") or "",
                "state": attrs.get("state_code") or "",
                "zip": attrs.get("postal_code") or "",
                "epa_region": attrs.get("epa_region") or "",
                "frs_registry_id": attrs.get("registry_id") or "",
                "acres_property_id": attrs.get("pgm_sys_id") or "",
                "latitude": _coerce_coordinate(attrs.get("latitude")),
                "longitude": _coerce_coordinate(attrs.get("longitude")),
                "facility_url": attrs.get("facility_url") or "",
            }
        )

    properties.sort(key=lambda p: (p["state"], p["city"], p["name"]))

    return {
        **base,
        "total": len(properties),
        "properties": properties,
        "warnings": list(result.warnings),
        "truncated": result.truncated,
    }


def _coerce_coordinate(value) -> float | None:
    """Return an attribute coordinate as a float, or None when absent or invalid."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_epa_acres_summary(result: Dict) -> str:
    """
    Format ACRES query results as a markdown summary for Brownfields screening.

    Args:
        result: Data dict from get_epa_acres_properties_in_roi().

    Returns:
        Formatted markdown string.
    """
    center = result.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = result.get("buffer_miles", 0)
    properties = result.get("properties", [])
    total = result.get("total", 0)
    lines = [
        "## EPA ACRES Brownfields Properties",
        "",
        f"**Location:** ({lat}, {lon})",
        f"**Buffer:** {buffer_miles} miles",
        f"**Total ACRES Properties:** {total}",
        "",
    ]

    if result.get("data_unavailable"):
        lines += ["> ⚠️ ACRES results are unavailable for this request, not a no-hit finding.", ""]

    if result.get("error"):
        lines += [f"> ⚠️ Error during query: {result['error']}", ""]

    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]

    if not properties:
        # An unavailable result must never render the no-hit sentence: the
        # banner above already labels it, and "No ... properties" would read
        # as a clean screen.
        if not result.get("data_unavailable"):
            lines += [
                "No ACRES Brownfields properties were identified within the ROI buffer.",
                "",
                "> **Screening Note:** ACRES contains only properties reported through EPA",
                "> Brownfields grant programs. An empty result is not evidence that the area",
                "> is free of brownfields or contamination.",
                "",
            ]
    else:
        # Group by state for readability
        by_state: Dict[str, list] = {}
        for prop in properties:
            state = prop.get("state") or "Unknown"
            by_state.setdefault(state, []).append(prop)

        listed = 0
        for state, state_props in sorted(by_state.items()):
            if listed >= MAX_LISTED_PROPERTIES:
                break
            property_label = "property" if len(state_props) == 1 else "properties"
            lines += [f"### {state} ({len(state_props)} {property_label})", ""]
            for prop in state_props:
                if listed >= MAX_LISTED_PROPERTIES:
                    break
                lines.append(_format_property_line(prop))
                listed += 1
            lines.append("")

        if total > MAX_LISTED_PROPERTIES:
            lines += [
                f"Listing the first {MAX_LISTED_PROPERTIES} of {total} properties (sorted by state, "
                "city, and property name). Reduce buffer_miles for a complete listing.",
                "",
            ]

    lines += [
        "---",
        "",
        "Data Source: EPA ACRES (Assessment, Cleanup and Redevelopment Exchange System) via the "
        f"EPA Envirofacts Brownfields ArcGIS layer ({ACRES_SERVICE_URL}/{ACRES_BROWNFIELDS_LAYER_ID}).",
        "Note: ACRES contains properties reported through EPA Brownfields grant programs; it is "
        "not a complete inventory of brownfields or contaminated sites.",
        "Note: An ACRES record is not a determination that land is contaminated, available, or "
        "suitable for development. Confirm site conditions through environmental site assessments "
        "and authoritative records.",
    ]

    return "\n".join(lines)


def _format_property_line(prop: Dict) -> str:
    """Render one ACRES property as a single markdown list item."""
    location = ", ".join(filter(None, [prop.get("address"), prop.get("city"), prop.get("county"), prop.get("zip")]))
    identifiers = " / ".join(
        filter(
            None,
            [
                f"FRS Registry ID {prop['frs_registry_id']}" if prop.get("frs_registry_id") else "",
                f"ACRES ID {prop['acres_property_id']}" if prop.get("acres_property_id") else "",
            ],
        )
    )
    coordinates = ""
    if prop.get("latitude") is not None and prop.get("longitude") is not None:
        coordinates = f"({prop['latitude']}, {prop['longitude']})"

    line = f"- **{prop.get('name') or 'Unknown'}**"
    details = " — ".join(filter(None, [location, prop.get("epa_region"), identifiers, coordinates]))
    if details:
        line += f" — {details}"
    if prop.get("facility_url"):
        line += f" — [EPA property record]({prop['facility_url']})"
    return line
