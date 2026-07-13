"""
Simple Python API for generating ROI GeoJSON

This module provides a clean API for generating Region of Interest (ROI)
GeoJSON data from latitude/longitude coordinates. File operations are omitted
so the API remains stateless.
"""

from datetime import datetime
from typing import Dict, Tuple

from nepa_mcp_common.arcgis import ArcGISService, calculate_area


def _format_extent(extent: Dict) -> Dict:
    """Convert ArcGIS extent to cardinal directions."""
    return {
        "north": round(extent["ymax"], 6),
        "south": round(extent["ymin"], 6),
        "east": round(extent["xmax"], 6),
        "west": round(extent["xmin"], 6),
    }


def _calculate_areas(buffer_geom: Dict) -> Tuple[float, float]:
    """Calculate area in both square miles and acres."""
    return (round(calculate_area(buffer_geom, "square_miles"), 2), round(calculate_area(buffer_geom, "acres"), 0))


def get_roi_geojson(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Generate GeoJSON only (no map image or file output).

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer distance in miles (default: 25)

    Returns:
        GeoJSON dictionary

    Example:
        >>> geojson = get_roi_geojson(40.7128, -74.0060, 25)
        >>> print(geojson['metadata']['area']['square_miles'])
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    area_sq_miles, area_acres = _calculate_areas(buffer_geom)
    extent = _format_extent(ArcGISService.get_extent_from_geometry(buffer_geom))

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"type": "Project Location", "latitude": lat, "longitude": lon},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": buffer_geom.get("rings", [])},
                "properties": {
                    "type": "Region of Interest",
                    "buffer_miles": buffer_miles,
                    "area_square_miles": area_sq_miles,
                    "area_acres": area_acres,
                },
            },
        ],
        "metadata": {
            "created": datetime.utcnow().isoformat(),
            "center": {"latitude": lat, "longitude": lon},
            "buffer_miles": buffer_miles,
            "area": {"square_miles": area_sq_miles, "acres": area_acres},
            "extent": extent,
        },
    }


def calculate_roi_area(lat: float, lon: float, buffer_miles: float = 25.0) -> Tuple[float, float]:
    """
    Calculate ROI area without generating files.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer distance in miles (default: 25)

    Returns:
        Tuple of (square_miles, acres)

    Example:
        >>> sq_mi, acres = calculate_roi_area(40.7128, -74.0060, 25)
        >>> print(f"Area: {sq_mi:.2f} square miles ({acres:,.0f} acres)")
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    return _calculate_areas(buffer_geom)


# =============================================================================
# Formatting helpers
# =============================================================================


def format_roi_summary(
    lat: float, lon: float, buffer_miles: float, sq_miles: float, acres: float, geojson: Dict, project_name: str = None
) -> str:
    """Format ROI data as a human-readable summary."""
    extent = geojson.get("metadata", {}).get("extent", {})

    lines = [
        "Region of Interest (ROI) Summary",
        "",
        f"Project: {project_name or 'Unnamed'}",
        f"Center: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        "",
        f"Area: {sq_miles:.2f} square miles ({acres:,.0f} acres)",
        "",
        "Extent:",
        f"  North: {extent.get('north', 'N/A')}",
        f"  South: {extent.get('south', 'N/A')}",
        f"  East: {extent.get('east', 'N/A')}",
        f"  West: {extent.get('west', 'N/A')}",
        "",
        "GeoJSON: Use the ROI GeoJSON tool for GIS import.",
        "",
        "Data Source: Calculated ROI buffer geometry",
    ]

    return "\n".join(lines)


def format_area_summary(lat: float, lon: float, buffer_miles: float, sq_miles: float, acres: float) -> str:
    """Format ROI area calculation as a human-readable summary."""
    lines = [
        "ROI Area Calculation",
        "",
        f"Center: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        "",
        f"Area: {sq_miles:.2f} square miles",
        f"      {acres:,.0f} acres",
        "",
        "Data Source: Calculated ROI buffer geometry",
    ]

    return "\n".join(lines)
