"""
USACE (U.S. Army Corps of Engineers) regulatory data utilities.

This module provides access to USACE regulatory boundaries and wetland delineation
regions for Section 404 Clean Water Act compliance analysis.

Data Sources:
- USACE Regulatory Boundaries: District jurisdiction for Section 404 permits
- COE Wetland Regions: Regional supplements to the Wetland Delineation Manual
- COE Wetland Subregions: Sub-regional wetland classifications
"""

from __future__ import annotations

from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService


# USACE ArcGIS REST Service URLs
USACE_REGULATORY_BOUNDARY_URL = (
    "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/usace_regulatory_boundary/FeatureServer"
)
USACE_WETLAND_REGIONS_URL = (
    "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_regions/FeatureServer"
)
USACE_WETLAND_SUBREGIONS_URL = (
    "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_subregions/FeatureServer"
)

# Layer indices
REGULATORY_BOUNDARY_LAYER = 0
WETLAND_REGIONS_LAYER = 0
WETLAND_SUBREGIONS_LAYER = 0


def _create_roi(lat: float, lon: float, buffer_miles: float) -> Dict:
    """Create the ROI polygon used by USACE FeatureServer queries."""
    return ArcGISService.create_roi_buffer(lat, lon, buffer_miles)


def _query_usace_features(
    base_url: str, layer_id: int, geometry: Dict, service_name: str
) -> tuple[list[Dict], list[str]]:
    """Query a USACE ArcGIS layer with shared pagination and warning handling."""
    result = ArcGISService.query_features(
        base_url,
        layer_id,
        geometry,
        out_fields="*",
        timeout=30,
        service_name=service_name,
    )
    return result.features, result.warnings


def get_usace_regulatory_district(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query USACE regulatory district boundaries within a Region of Interest.

    Identifies which USACE district(s) have regulatory jurisdiction over the ROI
    for Section 404 permit applications.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing:
        - center: Query center point
        - buffer_miles: Buffer distance
        - total_districts: Number of districts found
        - districts: List of district records with jurisdiction details
    """
    buffer_geom = _create_roi(lat, lon, buffer_miles)
    features, warnings = _query_usace_features(
        USACE_REGULATORY_BOUNDARY_URL,
        REGULATORY_BOUNDARY_LAYER,
        buffer_geom,
        "USACE Regulatory Boundary",
    )
    districts = []

    for feature in features:
        attrs = feature.get("attributes", {})

        # Map actual field names from USACE API
        district = {
            "district_name": attrs.get(
                "ERO_FORMALNAME", attrs.get("ENGINEER_REPORTING_ORG_NAME", attrs.get("DISTRICT", "Unknown"))
            ),
            "district_abbreviation": attrs.get(
                "DIST_ABBR", attrs.get("USACE_DISTRICT_CODE", attrs.get("AGENCY_CODE", ""))
            ),
            "division_name": attrs.get("REPORTS_TO", ""),
            "division_abbreviation": attrs.get("USACE_DIVISION_CODE", ""),
            "website_url": attrs.get("WEB_ADDR", ""),
            "phone": attrs.get("DISTRICT_N", ""),
            "address": attrs.get("DISTRICT_A", ""),
        }
        districts.append(district)

    # Remove duplicates by district name
    seen = set()
    unique_districts = []
    for d in districts:
        if d["district_name"] not in seen:
            seen.add(d["district_name"])
            unique_districts.append(d)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_districts": len(unique_districts),
        "districts": unique_districts,
        "warnings": warnings,
    }


def get_wetland_regions_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query wetland delineation regions within a Region of Interest.

    Identifies which Regional Supplements to the Corps of Engineers Wetland
    Delineation Manual apply to the project area.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing:
        - center: Query center point
        - buffer_miles: Buffer distance
        - total_regions: Number of wetland regions found
        - regions: List of wetland region records
    """
    buffer_geom = _create_roi(lat, lon, buffer_miles)
    features, warnings = _query_usace_features(
        USACE_WETLAND_REGIONS_URL,
        WETLAND_REGIONS_LAYER,
        buffer_geom,
        "USACE Wetland Regions",
    )
    regions = []

    # Regional supplement URL lookup (static mapping)
    supplement_urls = {
        "Arid West": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/4597/",
        "Great Plains": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/4636/",
        "Western Mountains, Valleys, and Coast": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7591/",
        "Atlantic and Gulf Coastal Plain": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7605/",
        "Midwest": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7617/",
        "Northcentral and Northeast": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7632/",
        "Alaska": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7645/",
        "Caribbean Islands": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7650/",
        "Hawaii and Pacific Islands": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7655/",
    }

    for feature in features:
        attrs = feature.get("attributes", {})

        region_name = attrs.get("REGION", "Unknown")
        region = {
            "region_name": region_name,
            "mlra_name": attrs.get("MLRA_NAME", ""),
            "lrr_name": attrs.get("LRR_NAME", ""),
            "supplement_url": supplement_urls.get(region_name, ""),
        }
        regions.append(region)

    # Remove duplicates by region name
    seen = set()
    unique_regions = []
    for r in regions:
        if r["region_name"] not in seen:
            seen.add(r["region_name"])
            unique_regions.append(r)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_regions": len(unique_regions),
        "regions": unique_regions,
        "warnings": warnings,
    }


def get_wetland_subregions_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query wetland subregions within a Region of Interest.

    Provides detailed sub-regional wetland classifications for precise
    delineation guidance.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing:
        - center: Query center point
        - buffer_miles: Buffer distance
        - total_subregions: Number of subregions found
        - subregions: List of subregion records
    """
    buffer_geom = _create_roi(lat, lon, buffer_miles)
    features, warnings = _query_usace_features(
        USACE_WETLAND_SUBREGIONS_URL,
        WETLAND_SUBREGIONS_LAYER,
        buffer_geom,
        "USACE Wetland Subregions",
    )
    subregions = []

    # Map regional supplement codes to region names
    region_map = {
        "AW": "Arid West",
        "GP": "Great Plains",
        "WMVC": "Western Mountains, Valleys, and Coast",
        "AGCP": "Atlantic and Gulf Coastal Plain",
        "MW": "Midwest",
        "NCNE": "Northcentral and Northeast",
        "AK": "Alaska",
        "CB": "Caribbean Islands",
        "HPI": "Hawaii and Pacific Islands",
    }

    for feature in features:
        attrs = feature.get("attributes", {})

        # Use ADS_SUB_NM for subregion name, MLRA_NAME as fallback
        subregion_name = attrs.get("ADS_SUB_NM", attrs.get("MLRA_NAME", "Unknown"))
        region_code = attrs.get("ADS_REGSUP", "")
        parent_region = region_map.get(region_code, region_code)

        subregion = {
            "subregion_name": subregion_name,
            "subregion_code": attrs.get("MLRARSYM", ""),
            "parent_region": parent_region,
            "mlra_name": attrs.get("MLRA_NAME", ""),
            "lrr_name": attrs.get("LRR_NAME", ""),
        }
        subregions.append(subregion)

    # Remove duplicates by subregion name
    seen = set()
    unique_subregions = []
    for s in subregions:
        if s["subregion_name"] not in seen:
            seen.add(s["subregion_name"])
            unique_subregions.append(s)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_subregions": len(unique_subregions),
        "subregions": unique_subregions,
        "warnings": warnings,
    }


def analyze_usace_jurisdiction(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Comprehensive USACE jurisdictional analysis for Section 404 compliance.

    Combines regulatory district, wetland region, and subregion data to provide
    a complete jurisdictional overview for NEPA/Clean Water Act analysis.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing comprehensive analysis results
    """
    # Query all three data sources
    districts_data = get_usace_regulatory_district(lat, lon, buffer_miles)
    regions_data = get_wetland_regions_in_roi(lat, lon, buffer_miles)
    subregions_data = get_wetland_subregions_in_roi(lat, lon, buffer_miles)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "regulatory_districts": districts_data,
        "wetland_regions": regions_data,
        "wetland_subregions": subregions_data,
    }


# =============================================================================
# Formatting helpers
# =============================================================================


def format_usace_districts_summary(districts_data: Dict) -> str:
    """Format USACE district data into a human-readable summary."""
    lat = districts_data["center"]["latitude"]
    lon = districts_data["center"]["longitude"]
    buffer = districts_data["buffer_miles"]
    total = districts_data["total_districts"]
    districts = districts_data.get("districts", [])

    lines = [
        "USACE Regulatory Districts",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        f"Districts Found: {total}",
        "",
    ]

    for warning in districts_data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    if districts:
        for d in districts:
            lines.append(f"**{d['district_name']}** ({d['district_abbreviation']})")
            if d.get("division_name"):
                lines.append(f"  Division: {d['division_name']} ({d.get('division_abbreviation', '')})")
            if d.get("phone"):
                lines.append(f"  Phone: {d['phone']}")
            if d.get("website_url"):
                lines.append(f"  Website: {d['website_url']}")
            lines.append("")
    else:
        lines.append("No USACE districts found in ROI.")

    lines.extend(
        [
            "Data Source: USACE Regulatory Boundaries",
            "Note: Contact the district Regulatory Office for Section 404 permit inquiries",
        ]
    )

    return "\n".join(lines)


def format_wetland_regions_summary(regions_data: Dict) -> str:
    """Format wetland regions data into a human-readable summary."""
    lat = regions_data["center"]["latitude"]
    lon = regions_data["center"]["longitude"]
    buffer = regions_data["buffer_miles"]
    total = regions_data["total_regions"]
    regions = regions_data.get("regions", [])

    lines = [
        "Wetland Delineation Regions",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        f"Regions Found: {total}",
        "",
    ]

    for warning in regions_data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    if regions:
        for r in regions:
            lines.append(f"**{r['region_name']}**")
            if r.get("mlra_name"):
                lines.append(f"  MLRA: {r['mlra_name']}")
            if r.get("lrr_name"):
                lines.append(f"  LRR: {r['lrr_name']}")
            if r.get("supplement_url"):
                lines.append(f"  Regional Supplement: {r['supplement_url']}")
            lines.append("")
    else:
        lines.append("No wetland regions found in ROI.")

    lines.extend(
        [
            "Data Source: USACE Regional Supplements to Wetland Delineation Manual",
            "Note: Use appropriate regional supplement for wetland delineation methodology",
        ]
    )

    return "\n".join(lines)


def format_wetland_subregions_summary(subregions_data: Dict) -> str:
    """Format wetland subregions data into a human-readable summary."""
    lat = subregions_data["center"]["latitude"]
    lon = subregions_data["center"]["longitude"]
    buffer = subregions_data["buffer_miles"]
    total = subregions_data["total_subregions"]
    subregions = subregions_data.get("subregions", [])

    lines = [
        "Wetland Subregion Classifications",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        f"Subregions Found: {total}",
        "",
    ]

    for warning in subregions_data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    if subregions:
        for s in subregions:
            lines.append(f"- {s.get('subregion_name', 'Unknown')} ({s.get('parent_region', 'Unknown')})")
    else:
        lines.append("No wetland subregions found in ROI.")

    lines.append("")
    lines.append("Data Source: USACE Wetland Subregions")

    return "\n".join(lines)


def format_comprehensive_analysis_summary(analysis_data: Dict) -> str:
    """Format comprehensive USACE analysis into a human-readable summary."""
    lat = analysis_data["center"]["latitude"]
    lon = analysis_data["center"]["longitude"]
    buffer = analysis_data["buffer_miles"]

    districts = analysis_data["regulatory_districts"].get("districts", [])
    regions = analysis_data["wetland_regions"].get("regions", [])
    subregions = analysis_data["wetland_subregions"].get("subregions", [])

    lines = [
        "USACE Jurisdictional Analysis",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        "",
        "Regulatory Districts:",
    ]

    for dataset in ("regulatory_districts", "wetland_regions", "wetland_subregions"):
        for warning in analysis_data[dataset].get("warnings", []):
            lines.extend([f"Warning: {warning}", ""])

    if districts:
        for d in districts:
            lines.append(f"- **{d['district_name']}** ({d['district_abbreviation']})")
            if d.get("website_url"):
                lines.append(f"  Website: {d['website_url']}")
    else:
        lines.append("- No districts found")

    lines.extend(["", "Wetland Delineation Regions:"])

    if regions:
        for r in regions:
            lines.append(f"- **{r['region_name']}**")
            if r.get("supplement_url"):
                lines.append(f"  Regional Supplement: {r['supplement_url']}")
    else:
        lines.append("- No wetland regions found")

    lines.extend(["", "Wetland Subregions:"])

    if subregions:
        for s in subregions:
            lines.append(f"- {s.get('subregion_name', 'Unknown')} ({s.get('parent_region', 'Unknown')})")
    else:
        lines.append("- No subregions found")

    lines.extend(
        [
            "",
            "Section 404 Compliance Notes:",
            "- Contact the identified USACE district for pre-application consultation",
            "- Use the applicable Regional Supplement for wetland delineation",
            "- Projects affecting waters of the U.S. require Section 404 permits",
            "- Nationwide permits may be available for minor impacts",
            "",
            "Data Sources: USACE Regulatory Boundaries, COE Wetland Regions/Subregions",
        ]
    )

    return "\n".join(lines)
