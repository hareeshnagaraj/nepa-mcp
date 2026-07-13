"""
Tribal land discovery utilities powered by Census TIGERweb AIANNHA layers.

This module provides access to American Indian/Alaska Native/Native Hawaiian Areas
(AIANNHA) data from Census TIGERweb for tribal consultation screening.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from nepa_mcp_common.arcgis import ArcGISService
from src.core.constants import (
    TIGERWEB_AIANNHA_URL,
    TRIBAL_LAYERS,
    SQ_METERS_TO_SQ_MILES,
)

logger = logging.getLogger(__name__)


def get_tribal_lands_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return tribal land designations intersecting the ROI.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with flat list of tribal lands and metadata.
        Each tribal land includes a 'category' field for grouping if needed.
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    tribal_lands, warnings = _query_tigerweb_tribal(buffer_geom)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(tribal_lands),
        "tribal_lands": tribal_lands,
        "warnings": warnings,
    }


def _query_tigerweb_tribal(buffer_geometry: Dict) -> tuple[List[Dict], List[str]]:
    """
    Get all tribal lands that intersect with the ROI buffer using Census TIGERweb AIANNHA.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        Flat list of tribal lands, sorted by name. Each item includes 'category' field.
    """
    all_tribal_lands = []
    warnings = []
    successful_layers = 0

    for layer_id, layer_name in TRIBAL_LAYERS.items():
        try:
            result = ArcGISService.query_features(
                TIGERWEB_AIANNHA_URL,
                layer_id,
                buffer_geometry,
                out_fields="NAME,BASENAME,GEOID,LSADC,AREALAND,CENTLAT,CENTLON",
                timeout=10,
                service_name=f"Census TIGERweb {layer_name}",
            )
            successful_layers += 1
            warnings.extend(result.warnings)

            for feature in result.features:
                attrs = feature.get("attributes", {})

                area_land = attrs.get("AREALAND")
                try:
                    area_sq_mi = float(area_land) / SQ_METERS_TO_SQ_MILES if area_land is not None else None
                except (TypeError, ValueError) as e:
                    logger.warning(f"Could not parse area for {attrs.get('NAME')}: {e}")
                    area_sq_mi = None

                all_tribal_lands.append(
                    {
                        "name": attrs.get("NAME", "Unknown"),
                        "basename": attrs.get("BASENAME", ""),
                        "geoid": attrs.get("GEOID", ""),
                        "type_code": attrs.get("LSADC", ""),
                        "area_sq_mi": round(area_sq_mi, 2) if area_sq_mi is not None else None,
                        "centroid_lat": attrs.get("CENTLAT"),
                        "centroid_lon": attrs.get("CENTLON"),
                        "category": layer_name,
                    }
                )

        except Exception as e:
            warning = f"{layer_name} layer query failed: {e}"
            logger.warning(warning)
            warnings.append(warning)

    if successful_layers == 0:
        warnings.append(
            "No TIGERweb tribal layers were queried successfully; results are unavailable, not a no-hit finding."
        )

    return sorted(all_tribal_lands, key=lambda x: (x.get("name") or "Unknown").lower()), warnings


def format_tribal_summary(tribal_data: Dict) -> str:
    """
    Format tribal lands data as a markdown summary.

    Args:
        tribal_data: Data from get_tribal_lands_in_roi()

    Returns:
        Formatted markdown string
    """
    center = tribal_data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = tribal_data.get("buffer_miles", 0)
    tribal_lands = tribal_data.get("tribal_lands", [])

    # Group by category for display
    by_category: Dict[str, List[Dict]] = {}
    for land in tribal_lands:
        by_category.setdefault(land["category"], []).append(land)

    lines = [
        "Tribal Lands within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Total Tribal Areas: {tribal_data.get('total', 0)}",
        "",
    ]

    for warning in tribal_data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    for category, lands in by_category.items():
        lines.append(f"{category} ({len(lands)}):")
        for land in lands:
            size = f"{land['area_sq_mi']:.2f} sq mi" if land.get("area_sq_mi") is not None else "Area N/A"
            lines.append(f"  - {land['name']} ({size})")
        lines.append("")

    if tribal_lands:
        lines.append(
            "Use these AIANNHA screening records to support consultation planning; verify obligations and contacts "
            "through agency and tribal coordination processes."
        )
    else:
        lines.append(
            "No tribal land records were returned. Absence of mapped AIANNHA records does not eliminate NHPA, "
            "EO 13175, or tribal consultation responsibilities."
        )

    return "\n".join(lines)
