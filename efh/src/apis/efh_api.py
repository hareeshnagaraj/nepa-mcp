"""
NOAA Essential Fish Habitat (EFH) query utilities for Magnuson-Stevens Act compliance.

Queries the public services used by NOAA's EFH Mapper reports to identify
Essential Fish Habitat, Habitat Areas of Particular Concern (HAPC), salmon
EFH by HUC-8 watershed, and Highly Migratory Species / Coastal Pelagic /
Groundfish EFH within a Region of Interest.

Data source: NOAA Fisheries EFH Mapper
  https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/EFH/FeatureServer
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.spatial import AreaUnit, clipped_union_area_from_esri_geometries
from nepa_mcp_common.validation import validate_coordinates
from src.core.constants import (
    EFH_MAPPER_EFH_LAYER_ID,
    EFH_MAPPER_EFH_SERVICE_URL,
    EFH_MAPPER_EFHA_LAYER_ID,
    EFH_MAPPER_EFHA_SERVICE_URL,
    EFH_MAPPER_HAPC_LAYER_ID,
    EFH_MAPPER_HAPC_SERVICE_URL,
    EFH_MAPPER_PACIFIC_SALMON_LAYER_ID,
    EFH_MAPPER_PACIFIC_SALMON_SERVICE_URL,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Out-fields per layer
# ---------------------------------------------------------------------------

_COMMON_OUT_FIELDS = (
    "SITENAME_L,LIFESTAGE,TYPE,FMC,LTTD_TITLE,LTTD_LINK_,"
    "ZONE,INSTATEWAT,ACRES,LTTD_TIT_1,FMC_REPORT,FMP_REPORT,"
    "DATACAVEAT,Region,LTTDT_LINK"
)

_HAPC_OUT_FIELDS = "HAPC_Siten,FisheryM_5,DataCaveat,FisheryMan,LinkToRegu"

_EFHA_OUT_FIELDS = "SITENAME_L,TYPE,LTTDT_LINK,FMC_REPORT,DATACAVEAT"

_SALMON_OUT_FIELDS = "HUC_8,HUC_8_Name,State,ChinookEFH,Coho_EFH,Pink_EFH,All_EFH"

_MARINE_SALMON_CAVEAT = (
    "> **Marine salmon EFH caveat:** This tool covers *freshwater* salmon EFH "
    "(HUC-8 watersheds) only. Marine salmon EFH is reported through the EFH "
    "species/management-unit layer. Review the EFH species results for coastal "
    "or marine project areas."
)


# =========================================================================
# Public query functions
# =========================================================================


def get_hapc_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return Habitat Areas of Particular Concern (HAPC) intersecting the ROI.

    HAPCs are subsets of EFH identified based on ecological importance,
    sensitivity to human activities, stress from development, or rarity.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, hapc list.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "hapc", "Buffer creation failed")

    features, warnings, _complete = _query_layer(
        EFH_MAPPER_HAPC_SERVICE_URL,
        EFH_MAPPER_HAPC_LAYER_ID,
        buffer_geom,
        _HAPC_OUT_FIELDS,
        "EFH Mapper HAPC",
    )
    hapc = _parse_hapc(features)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(hapc),
        "hapc": hapc,
        "warnings": warnings,
    }


def get_efh_areas_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return general EFH areas intersecting the ROI.

    EFH areas are waters and substrate necessary for fish spawning, breeding,
    feeding, or growth to maturity as defined under the Magnuson-Stevens Act.

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

    features, warnings, _complete = _query_layer(
        EFH_MAPPER_EFHA_SERVICE_URL,
        EFH_MAPPER_EFHA_LAYER_ID,
        buffer_geom,
        _EFHA_OUT_FIELDS,
        "EFH Mapper areas",
    )
    efh_areas = _parse_efha(features)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(efh_areas),
        "efh_areas": efh_areas,
        "warnings": warnings,
    }


def get_salmon_efh_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return salmon EFH by HUC-8 watershed intersecting the ROI.

    Identifies which HUC-8 watersheds contain EFH for Chinook, Coho,
    and Pink salmon.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, watersheds list.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "watersheds", "Buffer creation failed")

    features, warnings, _complete = _query_layer(
        EFH_MAPPER_PACIFIC_SALMON_SERVICE_URL,
        EFH_MAPPER_PACIFIC_SALMON_LAYER_ID,
        buffer_geom,
        _SALMON_OUT_FIELDS,
        "Pacific salmon EFH",
    )
    watersheds = _parse_salmon_efh(features)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(watersheds),
        "watersheds": watersheds,
        "warnings": warnings,
    }


def get_hms_cps_groundfish_efh_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return Highly Migratory Species, Coastal Pelagic, and Groundfish EFH in the ROI.

    Covers EFH designations for HMS (tunas, sharks, swordfish), Coastal Pelagic
    Species (sardine, anchovy, mackerel), and Pacific Coast Groundfish.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, and efh_areas list.
        Polygon acreage is unioned by designation and clipped to the ROI while
        source feature acreage remains separately available.
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)
    buffer_geom = _create_buffer(lat, lon, buffer_miles)
    if buffer_geom is None:
        return _empty_result(lat, lon, buffer_miles, "efh_areas", "Buffer creation failed")

    features, warnings, geometry_complete = _query_layer(
        EFH_MAPPER_EFH_SERVICE_URL,
        EFH_MAPPER_EFH_LAYER_ID,
        buffer_geom,
        _COMMON_OUT_FIELDS,
        "EFH Mapper species",
        return_geometry=True,
    )
    efh_areas = _deduplicate_efh(
        features,
        roi_geometry=buffer_geom,
        geometry_complete=geometry_complete,
    )
    _append_area_warnings(warnings, efh_areas)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(efh_areas),
        "efh_areas": efh_areas,
        "warnings": warnings,
    }


# =========================================================================
# Formatting helpers
# =========================================================================


def format_hapc_summary(result: Dict) -> str:
    center = result["center"]
    hapc = result.get("hapc", [])
    lines = [
        "## NOAA Habitat Areas of Particular Concern (HAPC)",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**HAPC designations found:** {result['total']}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not hapc:
        lines.append("No Habitat Areas of Particular Concern found within the ROI.")
    else:
        _append_efh_entries(lines, hapc)
        lines += [
            "---",
            "> **HAPC Note:** HAPCs are subsets of EFH identified as high priority for",
            "> conservation based on ecological importance, sensitivity, stress, or rarity.",
            "> Federal actions affecting HAPCs warrant heightened scrutiny under the",
            "> Magnuson-Stevens Act.",
        ]
    return "\n".join(lines)


def format_efh_areas_summary(result: Dict) -> str:
    center = result["center"]
    efh_areas = result.get("efh_areas", [])
    lines = [
        "## NOAA Essential Fish Habitat (EFH) Areas",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**EFH designations found:** {result['total']}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not efh_areas:
        lines.append("No Essential Fish Habitat areas found within the ROI.")
    else:
        _append_efh_entries(lines, efh_areas)
        lines += [
            "---",
            "> **EFH Note:** Under the Magnuson-Stevens Act (16 U.S.C. 1855(b)), federal",
            "> agencies must consult with NOAA Fisheries on actions that may adversely affect",
            "> Essential Fish Habitat.",
        ]
    return "\n".join(lines)


def format_salmon_efh_summary(result: Dict) -> str:
    center = result["center"]
    watersheds = result.get("watersheds", [])
    lines = [
        "## NOAA Salmon Essential Fish Habitat by HUC-8 Watershed",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**Watersheds with salmon EFH:** {result['total']}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not watersheds:
        lines += ["No **freshwater** salmon EFH watersheds found within the ROI.", "", _MARINE_SALMON_CAVEAT]
    else:
        lines.append("| HUC-8 | Watershed | State | Chinook | Coho | Pink | All |")
        lines.append("|-------|-----------|-------|---------|------|------|-----|")
        for w in watersheds:
            lines.append(
                f"| {w['huc_8']} | {w['huc_8_name']} | {w['state']} "
                f"| {w['chinook_efh']} | {w['coho_efh']} | {w['pink_efh']} "
                f"| {w['all_efh']} |"
            )
        lines.append("")
        lines += [
            "---",
            "> **Salmon EFH Note:** Freshwater EFH for Pacific salmon includes all streams,",
            "> lakes, ponds, wetlands, and other water bodies currently or historically",
            "> accessible to salmon in Washington, Oregon, Idaho, and California.",
        ]
    return "\n".join(lines)


def format_hms_cps_groundfish_summary(result: Dict) -> str:
    center = result["center"]
    efh_areas = result.get("efh_areas", [])
    lines = [
        "## NOAA HMS / Coastal Pelagic / Groundfish EFH",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**EFH designations found:** {result['total']}",
        "",
    ]
    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]
    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if not efh_areas:
        lines.append("No HMS/Coastal Pelagic/Groundfish EFH found within the ROI.")
    else:
        _append_efh_entries(lines, efh_areas)
        lines += [
            "---",
            "> **Note:** HMS includes tunas, sharks, and swordfish. Coastal Pelagic Species",
            "> include sardine, anchovy, and mackerel. Groundfish covers over 90 species of",
            "> rockfish, flatfish, and roundfish managed under the Pacific Coast Groundfish FMP.",
        ]
    return "\n".join(lines)


# =========================================================================
# Internal helpers
# =========================================================================


def _append_efh_entries(lines: List[str], entries: List[Dict]) -> None:
    by_fmc: Dict[str, List[Dict]] = {}
    for e in entries:
        fmc = e.get("fmc") or "Other"
        by_fmc.setdefault(fmc, []).append(e)

    for fmc, items in sorted(by_fmc.items()):
        lines.append(f"### {fmc}")
        lines.append("")
        for item in sorted(items, key=lambda x: (x.get("species", ""), x.get("lifestage", ""))):
            species = item.get("species") or "Unknown"
            lifestage = f" — {item['lifestage']}" if item.get("lifestage") else ""
            zone = f" (Zone: {item['zone']})" if item.get("zone") else ""
            if item.get("acres") is not None:
                if item.get("area_status") not in (None, "source_feature_attributes"):
                    label = "Partial area within ROI" if item.get("area_complete") is False else "Area within ROI"
                    acres = f" — {label}: {item['acres']:,.2f} acres"
                elif item.get("area_status") == "source_feature_attributes":
                    acres = f" — Reported source area: {item['acres']:,.2f} acres"
                else:
                    acres = f" — {item['acres']:,} acres"
            elif item.get("area_status"):
                acres = f" — Area within ROI: unavailable ({item['area_status']})"
            else:
                acres = ""
            lines.append(f"- **{species}**{lifestage}{zone}{acres}")
            if (
                item.get("area_status") not in (None, "source_feature_attributes")
                and item.get("source_acres") is not None
            ):
                lines.append(f"  Source feature-area total (not clipped to ROI): {item['source_acres']:,.2f} acres")
        lines.append("")


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
            service_name=f"NOAA {layer_name}",
            return_geometry=return_geometry,
            out_sr=4326 if return_geometry else None,
            simplify_geometry=not return_geometry,
        )
        return result.features, result.warnings, not result.truncated
    except Exception as e:
        warning = f"NOAA {layer_name} layer query failed: {e}"
        logger.warning(warning)
        return [], [warning], False


def _attr(attributes: Dict, *names: str, default=""):
    """Return an ArcGIS attribute using exact or case-insensitive matching."""
    for name in names:
        if name in attributes and attributes[name] is not None:
            return attributes[name]
    lower = {str(key).lower(): value for key, value in attributes.items()}
    for name in names:
        value = lower.get(name.lower())
        if value is not None:
            return value
    return default


def _deduplicate_efh(
    features: List[Dict],
    *,
    roi_geometry: Dict | None = None,
    geometry_complete: bool = True,
) -> List[Dict]:
    """Deduplicate EFH polygons and optionally clip grouped acreage to the ROI."""
    grouped: Dict[tuple, Dict] = {}
    geometries: Dict[tuple, List[Dict | None]] = {}
    for f in features:
        a = f.get("attributes", {})
        key = (
            _attr(a, "SITENAME_L", "sitename_l"),
            _attr(a, "LIFESTAGE", "lifestage"),
            _attr(a, "ZONE", "zone"),
            _attr(a, "TYPE", "type"),
        )
        if key not in grouped:
            grouped[key] = {
                "species": (_attr(a, "SITENAME_L", "sitename_l") or "").strip(),
                "lifestage": (_attr(a, "LIFESTAGE", "lifestage") or "").strip(),
                "type": _attr(a, "TYPE", "type") or "",
                "fmc": _attr(a, "FMC", "fmc") or "",
                "zone": _attr(a, "ZONE", "zone") or "",
                "in_state_waters": _attr(a, "INSTATEWAT", "instatewat") or "",
                "acres": 0,
                "title": _attr(a, "LTTD_TITLE", "lttd_title") or "",
                "title_detail": _attr(a, "LTTD_TIT_1", "lttd_tit_1") or "",
                "title_link": _attr(a, "LTTD_LINK_", "lttd_link_") or "",
                "detail_link": _attr(a, "LTTDT_LINK", "lttdt_link") or "",
                "fmc_report": _attr(a, "FMC_REPORT", "fmc_report") or "",
                "fmp_report": _attr(a, "FMP_REPORT", "fmp_report") or "",
                "data_caveat": _attr(a, "DATACAVEAT", "datacaveat") or "",
                "region": _attr(a, "Region", "region") or "",
            }
            geometries[key] = []
        grouped[key]["acres"] += _attr(a, "ACRES", "acres", default=0) or 0
        geometries[key].append(f.get("geometry"))

    result = list(grouped.values())
    for key, entry in grouped.items():
        source_acres = round(float(entry["acres"]), 2) if entry["acres"] else None
        entry["source_acres"] = source_acres
        if roi_geometry is None:
            entry["acres"] = source_acres
            entry["area_status"] = "source_feature_attributes"
            entry["area_complete"] = None
            entry["area_warnings"] = []
            continue

        area_result = clipped_union_area_from_esri_geometries(geometries[key], roi_geometry)
        entry["acres"] = area_result.area(AreaUnit.ACRES, rounded_digits=2)
        entry["area_status"] = area_result.status.value
        entry["area_complete"] = geometry_complete and area_result.complete
        entry["area_warnings"] = list(area_result.warnings)
        if not geometry_complete:
            entry["area_warnings"].append("ArcGIS truncated the matching feature set; clipped area may be understated.")
    return sorted(result, key=lambda x: (x.get("fmc", ""), x.get("species", "")))


def _append_area_warnings(warnings: List[str], records: List[Dict]) -> None:
    for record in records:
        label = record.get("species") or "Unnamed EFH designation"
        for area_warning in record.get("area_warnings", []):
            warning = f"{label} area: {area_warning}"
            if warning not in warnings:
                warnings.append(warning)


def _parse_hapc(features: List[Dict]) -> List[Dict]:
    """Parse the EFH Mapper HAPC layer into the common EFH output shape."""
    grouped: Dict[tuple, Dict] = {}
    for feature in features:
        attributes = feature.get("attributes", {})
        species = (_attr(attributes, "HAPC_Siten") or "").strip()
        fmc = _attr(attributes, "FisheryM_5", "FisheryMan") or ""
        key = (species, fmc)
        if key not in grouped:
            regulation_link = _attr(attributes, "LinkToRegu") or ""
            grouped[key] = {
                "species": species,
                "lifestage": "ALL",
                "type": "HAPC",
                "fmc": fmc,
                "zone": "",
                "in_state_waters": "",
                "acres": None,
                "title": "",
                "title_detail": "",
                "title_link": regulation_link,
                "detail_link": regulation_link,
                "fmc_report": _attr(attributes, "FisheryMan") or fmc,
                "fmp_report": "",
                "data_caveat": _attr(attributes, "DataCaveat") or "",
                "region": "",
            }
    return sorted(grouped.values(), key=lambda entry: (entry.get("fmc", ""), entry.get("species", "")))


def _parse_efha(features: List[Dict]) -> List[Dict]:
    """Parse the EFH Mapper EFHA layer into the common EFH output shape."""
    grouped: Dict[tuple, Dict] = {}
    for feature in features:
        attributes = feature.get("attributes", {})
        species = (_attr(attributes, "SITENAME_L") or "").strip()
        efh_type = _attr(attributes, "TYPE") or "EFHA"
        key = (species, efh_type)
        if key not in grouped:
            detail_link = _attr(attributes, "LTTDT_LINK") or ""
            grouped[key] = {
                "species": species,
                "lifestage": "ALL",
                "type": efh_type,
                "fmc": _attr(attributes, "FMC_REPORT") or "",
                "zone": "",
                "in_state_waters": "",
                "acres": None,
                "title": "",
                "title_detail": "",
                "title_link": detail_link,
                "detail_link": detail_link,
                "fmc_report": _attr(attributes, "FMC_REPORT") or "",
                "fmp_report": "",
                "data_caveat": _attr(attributes, "DATACAVEAT") or "",
                "region": "",
            }
    return sorted(grouped.values(), key=lambda entry: (entry.get("fmc", ""), entry.get("species", "")))


def _parse_salmon_efh(features: List[Dict]) -> List[Dict]:
    """Parse salmon EFH HUC-8 features, deduplicating by HUC code."""
    seen: Dict[int, Dict] = {}
    for f in features:
        a = f.get("attributes", {})
        huc = _attr(a, "HUC_8", "huc_8", default=None)
        if huc is None or huc in seen:
            continue
        seen[huc] = {
            "huc_8": huc,
            "huc_8_name": _attr(a, "HUC_8_Name", "huc_8_name") or "",
            "state": _attr(a, "State", "state") or "",
            "chinook_efh": _attr(a, "ChinookEFH", "chinookefh") or "",
            "coho_efh": _attr(a, "Coho_EFH", "coho_efh") or "",
            "pink_efh": _attr(a, "Pink_EFH", "pink_efh") or "",
            "all_efh": _attr(a, "All_EFH", "all_efh") or "",
        }
    return sorted(seen.values(), key=lambda w: w["huc_8_name"])
