"""
NOAA West Coast Region Critical Habitat query utilities for ESA Section 7 screening.

This module queries the NOAA Fisheries ArcGIS FeatureServer to identify
ESA-designated critical habitat within a Region of Interest. Used for
Endangered Species Act Section 7 consultation screening in NEPA analyses.

Data source: NOAA Fisheries West Coast Region
  https://maps.fisheries.noaa.gov/server/rest/services/Hosted/WCR_ch_dice/FeatureServer
"""

from __future__ import annotations

import logging
from typing import Dict, List

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.spatial import AreaUnit, clipped_union_area_from_esri_geometries
from nepa_mcp_common.validation import (
    NOAA_WEST_COAST_EXPECTED_BOUNDS,
    add_empty_result_coverage_warning,
    validate_coordinates,
)
from src.core.constants import NOAA_WCR_CH_SERVICE_URL, NOAA_WCR_CH_LAYERS

logger = logging.getLogger(__name__)

_LINE_OUT_FIELDS = (
    "comname,sciename,listentity,liststatus,chstatus,unit,taxon,habtype,frn,pubdate,effectdate,lengthkm,inporturl"
)

_POLY_OUT_FIELDS = (
    "comname,sciename,listentity,liststatus,chstatus,unit,taxon,habtype,frn,pubdate,effectdate,areasqkm,inporturl"
)


def get_noaa_critical_habitat_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return NOAA West Coast Region critical habitat intersecting the ROI.

    Queries both the line layer (layer 1, rivers/streams) and polygon layer
    (layer 2, marine/terrestrial) from the NOAA WCR critical habitat
    FeatureServer. Diced geometry fragments are de-duplicated by listed
    entity within each geometry layer, while preserving all distinct unit
    labels. Polygon areas are unioned and clipped to the ROI; their upstream
    whole-feature area attributes are retained separately for provenance.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with:
            - center: {latitude, longitude}
            - buffer_miles: float
            - total: int (unique habitat units)
            - habitats: list of habitat dicts
              Polygon records use ``area_sqkm`` for unioned area inside the ROI,
              ``source_area_sqkm`` for the upstream whole-feature total, and
              ``area_status``/``area_complete`` for measurement provenance.
            - species_count: int (unique species)
            - error: str (only present if buffer creation failed)
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
            "habitats": [],
            "species_count": 0,
            "error": str(e),
        }

    habitats, warnings = _query_noaa_ch_layers(buffer_geom)
    species = {h["listed_entity"] for h in habitats}
    named_units = {unit for habitat in habitats for unit in habitat.get("units", [])}

    result = {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(habitats),
        "habitats": habitats,
        "species_count": len(species),
        "designation_count": len(habitats),
        "named_unit_count": len(named_units),
        "warnings": warnings,
    }
    return add_empty_result_coverage_warning(
        result,
        buffer_geom,
        bounds=NOAA_WEST_COAST_EXPECTED_BOUNDS,
        dataset_name="NOAA Fisheries West Coast critical habitat",
    )


def _query_noaa_ch_layers(buffer_geometry: Dict) -> tuple[List[Dict], List[str]]:
    """
    Query NOAA critical habitat line and polygon layers, de-duplicate diced
    fragments, and return a sorted list.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer).

    Returns:
        De-duplicated, name-sorted list of critical habitat dicts.
    """
    all_habitats: List[Dict] = []
    warnings: List[str] = []
    successful_layers = 0

    for layer_id, layer_name in NOAA_WCR_CH_LAYERS.items():
        out_fields = _POLY_OUT_FIELDS if layer_id == 2 else _LINE_OUT_FIELDS

        try:
            result = ArcGISService.query_features(
                NOAA_WCR_CH_SERVICE_URL,
                layer_id,
                buffer_geometry,
                out_fields=out_fields,
                timeout=30,
                service_name=f"NOAA {layer_name}",
                return_geometry=layer_id == 2,
                out_sr=4326 if layer_id == 2 else None,
                simplify_geometry=False,
            )
            successful_layers += 1
            warnings.extend(result.warnings)

            deduped = _deduplicate_fragments(
                result.features,
                layer_id,
                layer_name,
                roi_geometry=buffer_geometry if layer_id == 2 else None,
                geometry_complete=not result.truncated,
            )
            for habitat in deduped:
                for area_warning in habitat.get("area_warnings", []):
                    warning = f"{habitat.get('listed_entity') or 'Unnamed designation'} area: {area_warning}"
                    if warning not in warnings:
                        warnings.append(warning)
            all_habitats.extend(deduped)

        except Exception as e:
            warning = f"{layer_name} layer query failed: {e}"
            logger.warning(warning)
            warnings.append(warning)

    if successful_layers == 0:
        warnings.append("No NOAA critical habitat layers were queried successfully; results are unavailable.")

    return sorted(all_habitats, key=lambda x: (x["common_name"], x["listed_entity"])), warnings


def _deduplicate_fragments(
    features: List[Dict],
    layer_id: int,
    layer_name: str,
    *,
    roi_geometry: Dict | None = None,
    geometry_complete: bool = True,
) -> List[Dict]:
    """
    Group diced geometry fragments by listed entity, summing area/length and
    retaining every distinct non-empty unit label.

    Args:
        features: Raw ArcGIS feature list.
        layer_id: Layer ID (1=lines, 2=polygons).
        layer_name: Human-readable layer name.
        roi_geometry: ESRI polygon to use for clipped polygon area. When omitted,
            the legacy source-attribute area is retained in ``area_sqkm``.
        geometry_complete: Whether ArcGIS returned every matching feature page.

    Returns:
        List of de-duplicated habitat dicts.
    """
    grouped: Dict[str, Dict] = {}
    units_seen: Dict[str, set[str]] = {}
    geometries: Dict[str, List[Dict | None]] = {}

    for feature in features:
        attrs = feature.get("attributes", {})
        key = attrs.get("listentity") or ""

        if key not in grouped:
            grouped[key] = {
                "common_name": attrs.get("comname") or "",
                "scientific_name": attrs.get("sciename") or "",
                "listed_entity": attrs.get("listentity") or "",
                "listing_status": attrs.get("liststatus") or "",
                "ch_status": attrs.get("chstatus") or "",
                "unit": "",
                "units": [],
                "unit_count": 0,
                "taxon": attrs.get("taxon") or "",
                "habitat_type": attrs.get("habtype") or "",
                "federal_register": attrs.get("frn") or "",
                "pub_date": attrs.get("pubdate") or "",
                "effective_date": attrs.get("effectdate") or "",
                "area_sqkm": 0.0,
                "length_km": 0.0,
                "inport_url": attrs.get("inporturl") or "",
                "geometry_type": layer_name,
            }
            units_seen[key] = set()
            geometries[key] = []

        unit = (attrs.get("unit") or "").strip()
        if unit:
            units_seen[key].add(unit)

        if layer_id == 2:
            grouped[key]["area_sqkm"] += attrs.get("areasqkm") or 0.0
            geometries[key].append(feature.get("geometry"))
        else:
            grouped[key]["length_km"] += attrs.get("lengthkm") or 0.0

    result = []
    for key, habitat in grouped.items():
        habitat["units"] = sorted(units_seen[key])
        habitat["unit_count"] = len(habitat["units"])
        habitat["unit"] = "; ".join(habitat["units"])
        source_area_sqkm = round(habitat["area_sqkm"], 2) if habitat["area_sqkm"] else None
        if layer_id == 2:
            habitat["source_area_sqkm"] = source_area_sqkm
            if roi_geometry is not None:
                area_result = clipped_union_area_from_esri_geometries(geometries[key], roi_geometry)
                habitat["area_sqkm"] = area_result.area(AreaUnit.SQUARE_KILOMETERS, rounded_digits=2)
                habitat["area_status"] = area_result.status.value
                habitat["area_complete"] = geometry_complete and area_result.complete
                habitat["area_warnings"] = list(area_result.warnings)
                if not geometry_complete:
                    habitat["area_warnings"].append(
                        "ArcGIS truncated the matching feature set; clipped area may be understated."
                    )
            else:
                habitat["area_sqkm"] = source_area_sqkm
                habitat["area_status"] = "source_feature_attributes"
                habitat["area_complete"] = None
                habitat["area_warnings"] = []
        else:
            habitat["area_sqkm"] = None
        habitat["length_km"] = round(habitat["length_km"], 2) if habitat["length_km"] else None
        result.append(habitat)

    return result


def format_noaa_critical_habitat_summary(result: Dict) -> str:
    """
    Format NOAA critical habitat query results as a markdown summary.

    Args:
        result: Data dict from get_noaa_critical_habitat_in_roi().

    Returns:
        Formatted markdown string.
    """
    center = result.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = result.get("buffer_miles", 0)
    habitats = result.get("habitats", [])
    total = result.get("total", 0)
    species_count = result.get("species_count", 0)

    lines = [
        "## NOAA Critical Habitat (West Coast Region) — ESA Section 7 Screening",
        "",
        f"**Location:** ({lat}, {lon})",
        f"**Buffer:** {buffer_miles} miles",
        f"**Critical habitat designation records:** {total}",
        f"**Listed Species with Critical Habitat:** {species_count}",
        f"**Distinct named units:** {result.get('named_unit_count', 0)}",
        "",
    ]

    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]

    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if result.get("coverage_warning"):
        lines += [f"> Warning: {result['coverage_warning']}", ""]

    if not habitats:
        lines += [
            "No NOAA West Coast Region critical habitat was identified within the ROI.",
            "",
            "> **Note:** This server covers West Coast Region designations only.",
            "> Additional critical habitat data may be available through USFWS IPaC",
            "> for terrestrial and freshwater species under FWS jurisdiction.",
        ]
    else:
        by_species: Dict[str, List[Dict]] = {}
        for h in habitats:
            entity = h.get("listed_entity") or "Unknown"
            by_species.setdefault(entity, []).append(h)

        for entity, records in sorted(by_species.items()):
            status = records[0].get("listing_status", "")
            taxon = records[0].get("taxon", "")
            sci_name = records[0].get("scientific_name", "")
            named_units = sorted({unit for record in records for unit in record.get("units", [])})
            total_area = sum(record.get("area_sqkm") or 0 for record in records)
            total_source_area = sum(record.get("source_area_sqkm") or 0 for record in records)
            total_length = sum(record.get("length_km") or 0 for record in records)
            lines += [
                f"### {entity} (*{sci_name}*) — {status}",
                f"Taxon: {taxon} | Named units: {len(named_units)}",
                "",
            ]
            for unit in named_units:
                lines.append(f"- {unit}")
            if not named_units:
                lines.append("- *(unnamed unit)*")
            area_records = [
                record for record in records if record.get("area_status") or record.get("area_sqkm") is not None
            ]
            has_clipped_status = any(
                record.get("area_status") not in (None, "source_feature_attributes") for record in area_records
            )
            if any(record.get("area_sqkm") is not None for record in area_records):
                label = "Area within ROI" if has_clipped_status else "Reported polygon area (source attribute)"
                lines.append(f"- {label}: {round(total_area, 2)} sq km")
            elif area_records:
                statuses = sorted({record.get("area_status", "unavailable") for record in area_records})
                lines.append(f"- Area within ROI: unavailable ({', '.join(statuses)})")
            if has_clipped_status and any(record.get("source_area_sqkm") is not None for record in records):
                lines.append(f"- Source feature-area total (not clipped to ROI): {round(total_source_area, 2)} sq km")
            if total_length:
                lines.append(f"- Intersecting line-feature length (source attribute): {round(total_length, 2)} km")
            lines.append("")

        fr_notices = {h["federal_register"] for h in habitats if h.get("federal_register")}
        if fr_notices:
            lines += ["**Federal Register Notices:** " + "; ".join(sorted(fr_notices)), ""]

        lines += [
            "---",
            "",
            "> **ESA Section 7 Note:** Federal actions that may affect designated critical",
            "> habitat require consultation with NOAA Fisheries under Section 7 of the",
            "> Endangered Species Act (16 U.S.C. 1536). Formal consultation is required",
            "> when the action may adversely modify critical habitat.",
        ]

    return "\n".join(lines)
