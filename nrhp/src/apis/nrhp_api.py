"""
National Register of Historic Places (NRHP) query utilities for Section 106 NHPA screening.

This module queries the NPS ArcGIS MapServer to identify historic properties
listed on or eligible for the National Register of Historic Places within a
Region of Interest. Used for Section 106 of the National Historic Preservation
Act (NHPA) compliance screening in NEPA analyses.

Data source: National Park Service Cultural Resources
  https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer
"""

from __future__ import annotations

import logging
from typing import Dict, List

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import validate_coordinates
from src.core.constants import NRHP_SERVICE_URL, NRHP_LAYERS

logger = logging.getLogger(__name__)

# Fields to request from the NRHP ArcGIS service
_OUT_FIELDS = "NRIS_Refnum,RESNAME,ResType,Address,City,County,State,CertDate,Is_NHL,STATUS,NARA_URL,IS_EXTANT"


def get_nrhp_properties_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return NRHP-listed historic properties intersecting the ROI.

    Queries both the point layer (layer 0) and polygon layer (layer 1) from the
    NPS NRHP ArcGIS MapServer. Duplicate entries (same NRIS_Refnum appearing in
    both layers) are de-duplicated, preferring the polygon record.

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
            - nhl_count: int  (National Historic Landmarks subset)
            - error: str  (only present if buffer creation failed)
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)

    try:
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    except Exception as e:
        logger.error("ArcGIS buffer creation failed: %s", e)
        return {
            "center": {"latitude": lat, "longitude": lon},
            "buffer_miles": buffer_miles,
            "total": 0,
            "properties": [],
            "nhl_count": 0,
            "error": str(e),
        }

    properties, warnings = _query_nrhp_layers(buffer_geom)
    nhl_count = sum(1 for p in properties if p.get("is_nhl") == "X")

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(properties),
        "properties": properties,
        "nhl_count": nhl_count,
        "warnings": warnings,
    }


def _query_nrhp_layers(buffer_geometry: Dict) -> tuple[List[Dict], List[str]]:
    """
    Query both NRHP point and polygon layers, de-duplicate, and return sorted list.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer).

    Returns:
        De-duplicated, name-sorted list of historic property dicts.
    """
    seen_refnums: set = set()
    all_properties: List[Dict] = []
    warnings: List[str] = []
    successful_layers = 0

    # Query polygon layer first (layer 1) so polygon records take precedence
    # during de-duplication, then points (layer 0) fill in any gaps.
    for layer_id in [1, 0]:
        layer_name = NRHP_LAYERS[layer_id]
        try:
            result = ArcGISService.query_features(
                NRHP_SERVICE_URL,
                layer_id,
                buffer_geometry,
                out_fields=_OUT_FIELDS,
                timeout=30,
                headers={"User-Agent": "nepa-mcp/0.1 (NEPA compliance research)"},
                service_name=f"NRHP {layer_name}",
            )
            successful_layers += 1
            warnings.extend(result.warnings)

            for feature in result.features:
                attrs = feature.get("attributes", {})
                refnum = attrs.get("NRIS_Refnum", "")

                # Skip duplicates already captured from the polygon layer
                if refnum and refnum in seen_refnums:
                    continue
                if refnum:
                    seen_refnums.add(refnum)

                all_properties.append(
                    {
                        "name": attrs.get("RESNAME") or "Unknown",
                        "resource_type": attrs.get("ResType") or "",
                        "address": attrs.get("Address") or "",
                        "city": attrs.get("City") or "",
                        "county": attrs.get("County") or "",
                        "state": attrs.get("State") or "",
                        "cert_date": attrs.get("CertDate") or "",
                        "is_nhl": attrs.get("Is_NHL") or "",
                        "status": attrs.get("STATUS") or "",
                        "is_extant": attrs.get("IS_EXTANT") or "",
                        "nris_refnum": refnum,
                        "nara_url": attrs.get("NARA_URL") or "",
                        "geometry_type": layer_name,
                    }
                )

        except Exception as e:
            warning = f"{layer_name} layer query failed: {e}"
            logger.warning(warning)
            warnings.append(warning)

    if successful_layers == 0:
        warnings.append("No NRHP layers were queried successfully; results are unavailable, not a no-hit finding.")

    return sorted(all_properties, key=lambda x: x["name"]), warnings


def format_nrhp_summary(result: Dict) -> str:
    """
    Format NRHP query results as a markdown summary for Section 106 NHPA screening.

    Args:
        result: Data dict from get_nrhp_properties_in_roi().

    Returns:
        Formatted markdown string.
    """
    center = result.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = result.get("buffer_miles", 0)
    properties = result.get("properties", [])
    total = result.get("total", 0)
    nhl_count = result.get("nhl_count", 0)

    lines = [
        "## National Register of Historic Places (NRHP) — Section 106 Screening",
        "",
        f"**Location:** ({lat}, {lon})",
        f"**Buffer:** {buffer_miles} miles",
        f"**Total NRHP Properties:** {total}",
        f"**National Historic Landmarks (NHL):** {nhl_count}",
        "",
    ]

    if result.get("error"):
        lines += [f"> ⚠️ Error during query: {result['error']}", ""]

    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]

    if not properties:
        lines += [
            "No NRHP-listed properties were identified within the ROI buffer.",
            "",
            "> **Section 106 Note:** Absence of listed properties does not eliminate",
            "> the need to consider eligible but unlisted properties. A professional",
            "> architectural historian survey may still be required.",
        ]
    else:
        # Group by state for readability
        by_state: Dict[str, List[Dict]] = {}
        for prop in properties:
            state = prop.get("state") or "Unknown"
            by_state.setdefault(state, []).append(prop)

        for state, state_props in sorted(by_state.items()):
            lines += [f"### {state} ({len(state_props)} properties)", ""]
            for prop in state_props:
                nhl_flag = " 🏛️ **NHL**" if prop.get("is_nhl") == "X" else ""
                location = ", ".join(filter(None, [prop.get("city"), prop.get("county")]))
                cert = f" — Listed: {prop['cert_date']}" if prop.get("cert_date") else ""
                url_part = f" — [NARA Record]({prop['nara_url']})" if prop.get("nara_url") else ""
                lines.append(
                    f"- **{prop['name']}**{nhl_flag}  *{prop.get('resource_type', '')}*  {location}{cert}{url_part}"
                )
            lines.append("")

        lines += [
            "---",
            "",
            "> **Section 106 Note:** Federal undertakings may require consultation with",
            "> the State Historic Preservation Office (SHPO) and affected tribes per",
            "> 36 CFR Part 800 for any property listed or eligible for the NRHP.",
        ]

    return "\n".join(lines)
