"""
County lookup utilities backed by Census TIGERweb.

This module isolates the logic for discovering every county intersecting a
Region of Interest (ROI) buffer so downstream services (CLI tools, MCP servers)
can remain small and purpose-built.
"""

from __future__ import annotations

from typing import Dict, List

from nepa_mcp_common.arcgis import ArcGISService


def get_counties_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Identify counties that intersect a circular ROI buffer.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer distance in miles (default 25).

    Returns:
        Dictionary containing metadata about the query and a list of counties.
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

    counties: List[Dict] = _query_tigerweb_counties(buffer_geom)

    counties_sorted = sorted(counties, key=lambda x: (x["state"], x["name"]))

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_counties": len(counties_sorted),
        "counties": counties_sorted,
    }


def _query_tigerweb_counties(buffer_geometry: Dict) -> List[Dict]:
    """
    Get all counties that intersect with the ROI buffer using Census TIGERweb.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        List of county dictionaries with name, state, FIPS code
    """
    # Census TIGERweb Counties service
    tigerweb_url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
    county_layer_id = 82  # Counties layer in TIGERweb

    result = ArcGISService.query_features(
        tigerweb_url,
        county_layer_id,
        buffer_geometry,
        out_fields="NAME,STATE,BASENAME,LSADC,GEOID,CENTLAT,CENTLON",
        return_geometry=False,
        timeout=30,
        service_name="Census TIGERweb counties",
    )
    if result.truncated:
        raise RuntimeError(" ".join(result.warnings))
    features = result.features

    # Process and format county data
    counties = []
    for feature in features:
        attrs = feature.get("attributes", {})
        counties.append(
            {
                "name": attrs.get("NAME", "Unknown"),
                "state": attrs.get("STATE", ""),
                "basename": attrs.get("BASENAME", ""),
                "type": attrs.get("LSADC", ""),  # Legal/Statistical Area Description Code
                "fips": attrs.get("GEOID", ""),
                "centroid_lat": attrs.get("CENTLAT"),
                "centroid_lon": attrs.get("CENTLON"),
            }
        )

    return counties


def format_counties_summary(counties_data: Dict, csv_path: str) -> str:
    """
    Format counties data as a markdown summary.

    Args:
        counties_data: Data from get_counties_in_roi()
        csv_path: Path to exported CSV file

    Returns:
        Formatted markdown string
    """
    center = counties_data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = counties_data.get("buffer_miles", 0)
    counties = counties_data.get("counties", [])

    lines = [
        "Counties within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Total Counties: {counties_data.get('total_counties', 0)}",
        "",
        "Counties List:",
    ]

    for county in counties:
        lines.append(f"- {county['name']}, State: {county['state']} (FIPS: {county['fips']})")

    lines.extend(
        [
            "",
            f"CSV Export: {csv_path}",
            "",
            "Use this list to scope jurisdictional coordination, permitting triggers, and engagement plans.",
        ]
    )

    return "\n".join(lines)
