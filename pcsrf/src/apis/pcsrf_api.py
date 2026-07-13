"""
NOAA PCSRF (Pacific Coastal Salmon Recovery Fund) query utilities.

Queries four NOAA Fisheries ArcGIS FeatureServer services to identify
ESA-listed species ranges, critical habitat, essential fish habitat,
and salmon recovery projects within a Region of Interest.

Data source: NOAA Fisheries
  https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import (
    PCSRF_PROJECT_EXPECTED_BOUNDS,
    add_empty_result_coverage_warning,
    validate_coordinates,
)
from src.core.constants import (
    PCSRF_SPECIES_RANGES_URL,
    PCSRF_SPECIES_RANGES_LAYER_ID,
    PCSRF_CRITICAL_HABITAT_POLY_URL,
    PCSRF_CRITICAL_HABITAT_POLY_LAYER_ID,
    PCSRF_CRITICAL_HABITAT_LINE_URL,
    PCSRF_CRITICAL_HABITAT_LINE_LAYER_ID,
    PCSRF_EFH_URL,
    PCSRF_EFH_LAYER_ID,
    PCSRF_PROJECTS_URL,
    PCSRF_PROJECTS_LAYER_ID,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Out-fields for each service
# ---------------------------------------------------------------------------

_RANGES_OUT_FIELDS = (
    "COMNAME,SCIENAME,LISTENTITY,DPSESU,LISTSTATUS,TAXON,"
    "LEADOFFICE,FEDREG,PUBDATE,EFFECTDATE,LIFESTAGE,BEHAVIOR,"
    "RNGEXT,INPORTURL,NMFSPAGE,Shape__Area"
)

_CH_POLY_OUT_FIELDS = (
    "COMNAME,SCIENAME,LISTENTITY,LISTSTATUS,CHSTATUS,UNIT,"
    "TAXON,LEADOFFICE,FR,PUBDATE,EFFECTDATE,AREASqKm,"
    "HABTYPE,INPORTURL"
)

_CH_LINE_OUT_FIELDS = (
    "COMNAME,SCIENAME,LISTENTITY,LISTSTATUS,CHSTATUS,UNIT,"
    "TAXON,LEADOFFICE,FR,PUBDATE,EFFECTDATE,"
    "HABTYPE,INPORTURL,Shape__Length"
)

_EFH_OUT_FIELDS = "GNIS_Name,TYPE,REGION,LINK,BUFF_DIST,Shape__Area"

_PROJECTS_OUT_FIELDS = (
    "PROJECT_REF,PROJECT_NAME,PROJECT_LEAD,PRIMARY_SUBGRANTEE,"
    "FFY,CATEGORY,SUBCATEGORY,STATUS,DESCRIPTION,"
    "PCSRF_FUNDS,STATE_FUNDS,START_DATE,END_DATE,LATITUDE,LONGITUDE"
)


# =========================================================================
# Public query functions
# =========================================================================


def get_species_ranges_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return NOAA ESA-listed species ranges intersecting the ROI.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, species list, and species_count.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "species", "Buffer creation failed")

    features, warnings = _query_layer(
        PCSRF_SPECIES_RANGES_URL,
        PCSRF_SPECIES_RANGES_LAYER_ID,
        buffer_geom,
        _RANGES_OUT_FIELDS,
        "PCSRF species ranges",
    )

    species = _parse_ranges(features)
    unique = {s["listed_entity"] for s in species}

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(species),
        "species": species,
        "species_count": len(unique),
        "warnings": warnings,
    }


def get_critical_habitat_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return NOAA critical habitat (lines + polygons) intersecting the ROI.

    Queries both the polygon layer (marine/terrestrial areas) and line layer
    (rivers/streams). Diced geometry fragments are de-duplicated by grouping
    on (listentity, unit), summing area/length.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, habitats list, species_count.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "habitats", "Buffer creation failed")

    poly_features, poly_warnings = _query_layer(
        PCSRF_CRITICAL_HABITAT_POLY_URL,
        PCSRF_CRITICAL_HABITAT_POLY_LAYER_ID,
        buffer_geom,
        _CH_POLY_OUT_FIELDS,
        "PCSRF critical habitat polygons",
    )
    line_features, line_warnings = _query_layer(
        PCSRF_CRITICAL_HABITAT_LINE_URL,
        PCSRF_CRITICAL_HABITAT_LINE_LAYER_ID,
        buffer_geom,
        _CH_LINE_OUT_FIELDS,
        "PCSRF critical habitat lines",
    )

    habitats = _deduplicate_ch_fragments(poly_features, "polygon")
    habitats.extend(_deduplicate_ch_fragments(line_features, "line"))
    habitats.sort(key=lambda h: (h["common_name"], h["unit"]))

    unique = {h["listed_entity"] for h in habitats}

    result = {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(habitats),
        "habitats": habitats,
        "species_count": len(unique),
        "warnings": poly_warnings + line_warnings,
    }
    return result


def get_efh_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return Essential Fish Habitat (EFH) areas intersecting the ROI.

    Queries the Atlantic salmon EFH/HAPC Buffer FeatureServer.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, efh_areas list.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "efh_areas", "Buffer creation failed")

    features, warnings = _query_layer(
        PCSRF_EFH_URL,
        PCSRF_EFH_LAYER_ID,
        buffer_geom,
        _EFH_OUT_FIELDS,
        "PCSRF EFH",
    )

    efh_areas = _parse_efh(features)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(efh_areas),
        "efh_areas": efh_areas,
        "warnings": warnings,
    }


def get_pcsrf_projects_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return PCSRF salmon recovery projects within the ROI.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, projects list, total_funding.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "projects", "Buffer creation failed")

    features, warnings = _query_layer(
        PCSRF_PROJECTS_URL,
        PCSRF_PROJECTS_LAYER_ID,
        buffer_geom,
        _PROJECTS_OUT_FIELDS,
        "PCSRF projects",
    )

    projects = _parse_projects(features)
    total_funding = sum(p.get("pcsrf_funds") or 0.0 for p in projects)

    result = {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(projects),
        "projects": projects,
        "total_pcsrf_funding": round(total_funding, 2),
        "warnings": warnings,
    }
    return add_empty_result_coverage_warning(
        result,
        buffer_geom,
        bounds=PCSRF_PROJECT_EXPECTED_BOUNDS,
        dataset_name="Pacific Coastal Salmon Recovery Fund projects",
    )


# =========================================================================
# Formatting helpers
# =========================================================================


def format_species_ranges_summary(result: Dict) -> str:
    center = result["center"]
    species = result.get("species", [])
    lines = [
        "## NOAA ESA-Listed Species Ranges",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**Listed species ranges found:** {result['total']}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not species:
        lines.append("No NOAA ESA-listed species ranges found within the ROI.")
    else:
        for s in species:
            status = s.get("listing_status", "")
            dps = f" — {s['dps_esu']}" if s.get("dps_esu") else ""
            lines.append(f"- **{s['listed_entity']}** (*{s['scientific_name']}*) — {status}{dps}")
        lines.append("")
        lines += [
            "---",
            "> **Note:** Species ranges indicate where a species may occur, not confirmed",
            "> presence. Use in conjunction with critical habitat data for Section 7 screening.",
        ]
    return "\n".join(lines)


def format_critical_habitat_summary(result: Dict) -> str:
    center = result["center"]
    habitats = result.get("habitats", [])
    lines = [
        "## NOAA Critical Habitat — ESA Section 7 Screening",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**Critical habitat units:** {result['total']}",
        f"**Listed species with critical habitat:** {result.get('species_count', 0)}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not habitats:
        lines.append("No NOAA critical habitat found within the ROI.")
    else:
        by_species: Dict[str, List[Dict]] = {}
        for h in habitats:
            entity = h.get("listed_entity") or "Unknown"
            by_species.setdefault(entity, []).append(h)

        for entity, units in sorted(by_species.items()):
            first = units[0]
            lines += [
                f"### {entity} (*{first.get('scientific_name', '')}*) — {first.get('listing_status', '')}",
                f"Taxon: {first.get('taxon', '')} | Units: {len(units)}",
                "",
            ]
            for u in sorted(units, key=lambda x: x["unit"]):
                size = ""
                if u.get("area_sqkm"):
                    size = f" — {u['area_sqkm']} sq km"
                elif u.get("length_km"):
                    size = f" — {u['length_km']} km"
                hab = f" ({u['habitat_type']})" if u.get("habitat_type") else ""
                lines.append(f"- **{u['unit']}**{hab}{size}")
            lines.append("")

        lines += [
            "---",
            "> **ESA Section 7 Note:** Federal actions that may affect designated critical",
            "> habitat require consultation with NOAA Fisheries under Section 7 of the",
            "> Endangered Species Act (16 U.S.C. 1536).",
        ]
    return "\n".join(lines)


def format_efh_summary(result: Dict) -> str:
    center = result["center"]
    efh_areas = result.get("efh_areas", [])
    lines = [
        "## NOAA Essential Fish Habitat (EFH)",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**EFH areas found:** {result['total']}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not efh_areas:
        lines.append("No Essential Fish Habitat areas found within the ROI.")
    else:
        for area in efh_areas:
            name = area.get("gnis_name") or "Unnamed"
            efh_type = area.get("type", "")
            region = area.get("region", "")
            lines.append(f"- **{name}** — Type: {efh_type}, Region: {region}")
        lines.append("")
        lines += [
            "---",
            "> **EFH Note:** Under the Magnuson-Stevens Act, federal agencies must consult",
            "> with NOAA Fisheries on actions that may adversely affect Essential Fish Habitat.",
        ]
    return "\n".join(lines)


def format_pcsrf_projects_summary(result: Dict) -> str:
    center = result["center"]
    projects = result.get("projects", [])
    lines = [
        "## PCSRF Salmon Recovery Projects",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**Projects found:** {result['total']}",
        f"**Total PCSRF funding:** ${result.get('total_pcsrf_funding', 0):,.2f}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if result.get("coverage_warning"):
        lines += [f"> Warning: {result['coverage_warning']}", ""]
    if not projects:
        lines.append("No PCSRF projects found within the ROI.")
    else:
        by_status: Dict[str, List[Dict]] = {}
        for p in projects:
            status = p.get("status") or "Unknown"
            by_status.setdefault(status, []).append(p)

        for status, projs in sorted(by_status.items()):
            lines.append(f"### {status} ({len(projs)} projects)")
            lines.append("")
            for p in sorted(projs, key=lambda x: x.get("project_name", "")):
                funding = f" — ${p['pcsrf_funds']:,.0f}" if p.get("pcsrf_funds") else ""
                lines.append(f"- **{p.get('project_name', 'Unnamed')}**{funding}")
                if p.get("description"):
                    desc = p["description"][:200]
                    lines.append(f"  {desc}")
            lines.append("")

        lines += [
            "---",
            "> **PCSRF Note:** The Pacific Coastal Salmon Recovery Fund supports",
            "> conservation and restoration of Pacific salmon and steelhead populations.",
        ]
    return "\n".join(lines)


# =========================================================================
# Internal helpers
# =========================================================================


def _create_buffer(lat: float, lon: float, buffer_miles: float) -> Optional[Dict]:
    try:
        return ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    except Exception as e:
        logger.error("ArcGIS buffer creation failed: %s", e)
        return None


def _empty_result(lat: float, lon: float, buffer_miles: float, key: str, error: str) -> Dict:
    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": 0,
        key: [],
        "error": error,
    }


def _query_layer(
    service_url: str,
    layer_id: int,
    buffer_geom: Dict,
    out_fields: str,
    layer_name: str,
) -> tuple[List[Dict], List[str]]:
    try:
        result = ArcGISService.query_features(
            service_url,
            layer_id,
            buffer_geom,
            out_fields=out_fields,
            timeout=30,
            service_name=layer_name,
        )
        return result.features, result.warnings
    except Exception as e:
        warning = f"{layer_name} query failed: {e}"
        logger.warning(warning)
        return [], [warning]


def _parse_ranges(features: List[Dict]) -> List[Dict]:
    seen: Dict[str, Dict] = {}
    for f in features:
        a = f.get("attributes", {})
        entity = a.get("LISTENTITY") or ""
        if entity in seen:
            continue
        seen[entity] = {
            "common_name": a.get("COMNAME") or "",
            "scientific_name": a.get("SCIENAME") or "",
            "listed_entity": entity,
            "dps_esu": a.get("DPSESU") or "",
            "listing_status": a.get("LISTSTATUS") or "",
            "taxon": a.get("TAXON") or "",
            "lead_office": a.get("LEADOFFICE") or "",
            "federal_register": a.get("FEDREG") or "",
            "pub_date": a.get("PUBDATE") or "",
            "effective_date": a.get("EFFECTDATE") or "",
            "life_stage": a.get("LIFESTAGE") or "",
            "behavior": a.get("BEHAVIOR") or "",
            "range_extent": a.get("RNGEXT") or "",
            "inport_url": a.get("INPORTURL") or "",
            "species_page": a.get("NMFSPAGE") or "",
        }
    return sorted(seen.values(), key=lambda s: s["common_name"])


def _deduplicate_ch_fragments(features: List[Dict], geom_type: str) -> List[Dict]:
    grouped: Dict[tuple, Dict] = {}
    for f in features:
        a = f.get("attributes", {})
        key = (a.get("LISTENTITY", ""), a.get("UNIT", ""))
        if key not in grouped:
            grouped[key] = {
                "common_name": a.get("COMNAME") or "",
                "scientific_name": a.get("SCIENAME") or "",
                "listed_entity": a.get("LISTENTITY") or "",
                "listing_status": a.get("LISTSTATUS") or "",
                "ch_status": a.get("CHSTATUS") or "",
                "unit": a.get("UNIT") or "",
                "taxon": a.get("TAXON") or "",
                "habitat_type": a.get("HABTYPE") or "",
                "federal_register": a.get("FR") or "",
                "pub_date": a.get("PUBDATE") or "",
                "effective_date": a.get("EFFECTDATE") or "",
                "area_sqkm": 0.0,
                "length_km": 0.0,
                "inport_url": a.get("INPORTURL") or "",
                "geometry_type": geom_type,
            }
        if geom_type == "polygon":
            grouped[key]["area_sqkm"] += a.get("AREASqKm") or 0.0
        else:
            length_deg = a.get("Shape__Length") or 0.0
            grouped[key]["length_km"] += length_deg * 111.0

    result = []
    for h in grouped.values():
        h["area_sqkm"] = round(h["area_sqkm"], 2) if h["area_sqkm"] else None
        h["length_km"] = round(h["length_km"], 2) if h["length_km"] else None
        result.append(h)
    return result


def _parse_efh(features: List[Dict]) -> List[Dict]:
    areas = []
    for f in features:
        a = f.get("attributes", {})
        areas.append(
            {
                "gnis_name": a.get("GNIS_Name") or "",
                "type": a.get("TYPE") or "",
                "region": a.get("REGION") or "",
                "link": a.get("LINK") or "",
                "buffer_dist": a.get("BUFF_DIST"),
                "area_sq_units": a.get("Shape__Area"),
            }
        )
    return sorted(areas, key=lambda x: x["gnis_name"])


def _parse_projects(features: List[Dict]) -> List[Dict]:
    projects = []
    for f in features:
        a = f.get("attributes", {})
        projects.append(
            {
                "project_ref": a.get("PROJECT_REF") or "",
                "project_name": a.get("PROJECT_NAME") or "",
                "project_lead": a.get("PROJECT_LEAD") or "",
                "primary_subgrantee": a.get("PRIMARY_SUBGRANTEE") or "",
                "fiscal_year": a.get("FFY"),
                "category": a.get("CATEGORY") or "",
                "subcategory": a.get("SUBCATEGORY") or "",
                "status": a.get("STATUS") or "",
                "description": a.get("DESCRIPTION") or "",
                "pcsrf_funds": a.get("PCSRF_FUNDS"),
                "state_funds": a.get("STATE_FUNDS"),
                "start_date": a.get("START_DATE"),
                "end_date": a.get("END_DATE"),
                "latitude": a.get("LATITUDE"),
                "longitude": a.get("LONGITUDE"),
            }
        )
    return sorted(projects, key=lambda p: p.get("project_name", ""))
