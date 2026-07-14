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
from nepa_mcp_common.spatial import AreaUnit, clipped_union_area_from_esri_geometries
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

    features, warnings, _complete = _query_layer(
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
        Dictionary with center, buffer_miles, total, habitats list, and
        species_count. Polygon records distinguish ROI-clipped area from source
        feature area; line records retain source length only.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "habitats", "Buffer creation failed")

    poly_features, poly_warnings, poly_complete = _query_layer(
        PCSRF_CRITICAL_HABITAT_POLY_URL,
        PCSRF_CRITICAL_HABITAT_POLY_LAYER_ID,
        buffer_geom,
        _CH_POLY_OUT_FIELDS,
        "PCSRF critical habitat polygons",
        return_geometry=True,
    )
    line_features, line_warnings, _line_complete = _query_layer(
        PCSRF_CRITICAL_HABITAT_LINE_URL,
        PCSRF_CRITICAL_HABITAT_LINE_LAYER_ID,
        buffer_geom,
        _CH_LINE_OUT_FIELDS,
        "PCSRF critical habitat lines",
    )

    habitats = _deduplicate_ch_fragments(
        poly_features,
        "polygon",
        roi_geometry=buffer_geom,
        geometry_complete=poly_complete,
    )
    habitats.extend(_deduplicate_ch_fragments(line_features, "line"))
    habitats.sort(key=lambda h: (h["common_name"], h["unit"]))

    unique = {h["listed_entity"] for h in habitats}

    warnings = poly_warnings + line_warnings
    _append_area_warnings(warnings, habitats, label_key="listed_entity")
    if any(habitat.get("length_km") is not None for habitat in habitats):
        warnings.append(
            "Critical-habitat line length is a legacy source-coordinate estimate; "
            "it is not a geodesic length clipped to the ROI."
        )
    result = {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(habitats),
        "habitats": habitats,
        "species_count": len(unique),
        "warnings": warnings,
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
        Dictionary with center, buffer_miles, total, and efh_areas list. Each
        polygon record includes area inside the ROI plus status/completeness;
        the raw service area attribute remains separately available.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "efh_areas", "Buffer creation failed")

    features, warnings, geometry_complete = _query_layer(
        PCSRF_EFH_URL,
        PCSRF_EFH_LAYER_ID,
        buffer_geom,
        _EFH_OUT_FIELDS,
        "PCSRF EFH",
        return_geometry=True,
    )

    efh_areas = _parse_efh(
        features,
        roi_geometry=buffer_geom,
        geometry_complete=geometry_complete,
    )
    _append_area_warnings(warnings, efh_areas, label_key="gnis_name")

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

    features, warnings, _complete = _query_layer(
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
                if u.get("area_sqkm") is not None:
                    if u.get("area_complete") is False:
                        label = "partial area within ROI"
                    else:
                        label = (
                            "within ROI"
                            if u.get("area_status") not in (None, "source_feature_attributes")
                            else "source area"
                        )
                    size = f" — {u['area_sqkm']} sq km {label}"
                elif u.get("area_status"):
                    size = f" — area unavailable ({u['area_status']})"
                elif u.get("length_km"):
                    size = f" — {u['length_km']} km (legacy estimate; not ROI-clipped)"
                hab = f" ({u['habitat_type']})" if u.get("habitat_type") else ""
                lines.append(f"- **{u['unit']}**{hab}{size}")
                if (
                    u.get("area_status") not in (None, "source_feature_attributes")
                    and u.get("source_area_sqkm") is not None
                ):
                    lines.append(f"  Source feature-area total (not clipped to ROI): {u['source_area_sqkm']} sq km")
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
            area_note = ""
            if area.get("area_acres") is not None:
                label = "Partial area within ROI" if area.get("area_complete") is False else "Area within ROI"
                area_note = f", {label}: {area['area_acres']:,.2f} acres"
            elif area.get("area_status"):
                area_note = f", Area within ROI: unavailable ({area['area_status']})"
            lines.append(f"- **{name}** — Type: {efh_type}, Region: {region}{area_note}")
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
    *,
    return_geometry: bool = False,
) -> tuple[List[Dict], List[str], bool]:
    try:
        result = ArcGISService.query_features(
            service_url,
            layer_id,
            buffer_geom,
            out_fields=out_fields,
            timeout=30,
            service_name=layer_name,
            return_geometry=return_geometry,
            out_sr=4326 if return_geometry else None,
            simplify_geometry=not return_geometry,
        )
        return result.features, result.warnings, not result.truncated
    except Exception as e:
        warning = f"{layer_name} query failed: {e}"
        logger.warning(warning)
        return [], [warning], False


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


def _deduplicate_ch_fragments(
    features: List[Dict],
    geom_type: str,
    *,
    roi_geometry: Dict | None = None,
    geometry_complete: bool = True,
) -> List[Dict]:
    grouped: Dict[tuple, Dict] = {}
    geometries: Dict[tuple, List[Dict | None]] = {}
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
            geometries[key] = []
        if geom_type == "polygon":
            grouped[key]["area_sqkm"] += a.get("AREASqKm") or 0.0
            geometries[key].append(f.get("geometry"))
        else:
            length_deg = a.get("Shape__Length") or 0.0
            grouped[key]["length_km"] += length_deg * 111.0

    result = []
    for key, h in grouped.items():
        source_area = round(h["area_sqkm"], 2) if h["area_sqkm"] else None
        if geom_type == "polygon":
            h["source_area_sqkm"] = source_area
            _set_area_fields(
                h,
                geometries[key],
                roi_geometry=roi_geometry,
                geometry_complete=geometry_complete,
                unit=AreaUnit.SQUARE_KILOMETERS,
                output_key="area_sqkm",
                source_value=source_area,
            )
        else:
            h["area_sqkm"] = None
        h["length_km"] = round(h["length_km"], 2) if h["length_km"] else None
        result.append(h)
    return result


def _parse_efh(
    features: List[Dict],
    *,
    roi_geometry: Dict | None = None,
    geometry_complete: bool = True,
) -> List[Dict]:
    if roi_geometry is None:
        # Preserve the historical one-output-per-input helper contract for
        # direct Python callers. Production point-buffer calls pass an ROI and
        # use the grouped union/clip path below.
        return sorted(
            [
                {
                    "gnis_name": feature.get("attributes", {}).get("GNIS_Name") or "",
                    "type": feature.get("attributes", {}).get("TYPE") or "",
                    "region": feature.get("attributes", {}).get("REGION") or "",
                    "link": feature.get("attributes", {}).get("LINK") or "",
                    "buffer_dist": feature.get("attributes", {}).get("BUFF_DIST"),
                    "area_sq_units": feature.get("attributes", {}).get("Shape__Area"),
                }
                for feature in features
            ],
            key=lambda entry: entry["gnis_name"],
        )

    grouped: Dict[tuple, Dict] = {}
    geometries: Dict[tuple, List[Dict | None]] = {}
    for f in features:
        a = f.get("attributes", {})
        key = (
            a.get("GNIS_Name") or "",
            a.get("TYPE") or "",
            a.get("REGION") or "",
            a.get("LINK") or "",
            a.get("BUFF_DIST"),
        )
        if key not in grouped:
            grouped[key] = {
                "gnis_name": a.get("GNIS_Name") or "",
                "type": a.get("TYPE") or "",
                "region": a.get("REGION") or "",
                "link": a.get("LINK") or "",
                "buffer_dist": a.get("BUFF_DIST"),
                "area_sq_units": a.get("Shape__Area"),
            }
            geometries[key] = []
        elif a.get("Shape__Area"):
            grouped[key]["area_sq_units"] = (grouped[key].get("area_sq_units") or 0) + a["Shape__Area"]
        geometries[key].append(f.get("geometry"))

    areas = []
    for key, entry in grouped.items():
        _set_area_fields(
            entry,
            geometries[key],
            roi_geometry=roi_geometry,
            geometry_complete=geometry_complete,
            unit=AreaUnit.ACRES,
            output_key="area_acres",
            source_value=None,
        )
        areas.append(entry)
    return sorted(areas, key=lambda x: x["gnis_name"])


def _set_area_fields(
    entry: Dict,
    geometries: List[Dict | None],
    *,
    roi_geometry: Dict | None,
    geometry_complete: bool,
    unit: AreaUnit,
    output_key: str,
    source_value: float | None,
) -> None:
    """Populate clipped-area status fields while preserving legacy parser behavior."""
    if roi_geometry is None:
        entry[output_key] = source_value
        entry["area_status"] = "source_feature_attributes"
        entry["area_complete"] = None
        entry["area_warnings"] = []
        return

    area_result = clipped_union_area_from_esri_geometries(geometries, roi_geometry)
    entry[output_key] = area_result.area(unit, rounded_digits=2)
    entry["area_status"] = area_result.status.value
    entry["area_complete"] = geometry_complete and area_result.complete
    entry["area_warnings"] = list(area_result.warnings)
    if not geometry_complete:
        entry["area_warnings"].append("ArcGIS truncated the matching feature set; clipped area may be understated.")


def _append_area_warnings(warnings: List[str], records: List[Dict], *, label_key: str) -> None:
    for record in records:
        label = record.get(label_key) or "Unnamed feature"
        for area_warning in record.get("area_warnings", []):
            warning = f"{label} area: {area_warning}"
            if warning not in warnings:
                warnings.append(warning)


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
