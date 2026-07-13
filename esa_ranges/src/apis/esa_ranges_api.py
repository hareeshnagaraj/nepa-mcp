"""
NOAA ESA Species Ranges query utilities for ESA Section 7 screening.

Queries the NOAA Fisheries West Coast Region Ranges_dice FeatureServer
to identify ESA-listed species ranges (with HUC-12 watershed detail)
within a Region of Interest.

Data source: NOAA Fisheries West Coast Region
  https://maps.fisheries.noaa.gov/server/rest/services/Hosted/Ranges_dice/FeatureServer
"""

from __future__ import annotations

import logging
from typing import Dict, List

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import (
    NOAA_WEST_COAST_EXPECTED_BOUNDS,
    add_empty_result_coverage_warning,
    validate_coordinates,
)
from src.core.constants import (
    ESA_RANGES_FISH_LAYER_ID,
    ESA_RANGES_LAYER_ID,
    ESA_RANGES_SERVICE_URL,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Coded-value domain lookups (from FeatureServer field metadata)
# ---------------------------------------------------------------------------

_LISTENTITY = {
    "CKCAC": "Salmon, Chinook (California Coastal ESU)",
    "CKCAC_Out": "Salmon, Chinook (California Coastal ESU) - Outside range",
    "CKCVS": "Salmon, Chinook (Central Valley spring-run ESU)",
    "CKCVS_Out": "Salmon, Chinook (Central Valley spring-run ESU) - Outside range",
    "CKCVX": "Salmon, Chinook (Central Valley spring-run ESU--XN)",
    "CKCVX_Out": "Salmon, Chinook (Central Valley spring-run ESU--XN) - Outside range",
    "CKLCR": "Salmon, Chinook (Lower Columbia River ESU)",
    "CKLCR_Out": "Salmon, Chinook (Lower Columbia River ESU) - Outside range",
    "CKPUG": "Salmon, Chinook (Puget Sound ESU)",
    "CKPUG_Out": "Salmon, Chinook (Puget Sound ESU) - Outside range",
    "CKSAC": "Salmon, Chinook (Sacramento River winter-run ESU)",
    "CKSAC_Out": "Salmon, Chinook (Sacramento River winter-run ESU) - Outside range",
    "CKSRF": "Salmon, Chinook (Snake River fall-run ESU)",
    "CKSRF_Out": "Salmon, Chinook (Snake River fall-run ESU) - Outside range",
    "CKSRS": "Salmon, Chinook (Snake River spring/summer-run ESU)",
    "CKSRS_Out": "Salmon, Chinook (Snake River spring/summer-run ESU) - Outside range",
    "CKUCS": "Salmon, Chinook (Upper Columbia River spring-run ESU)",
    "CKUCS_Out": "Salmon, Chinook (Upper Columbia River spring-run ESU) - Outside range",
    "CKUCX": "Salmon, Chinook (Upper Columbia River spring-run ESU--XN)",
    "CKUCX_Out": "Salmon, Chinook (Upper Columbia River spring-run ESU--XN) - Outside range",
    "CKUWR": "Salmon, Chinook (Upper Willamette River ESU)",
    "CKUWR_Out": "Salmon, Chinook (Upper Willamette River ESU) - Outside range",
    "CMCOL": "Salmon, chum (Columbia River ESU)",
    "CMCOL_Out": "Salmon, chum (Columbia River ESU) - Outside range",
    "CMHCS": "Salmon, chum (Hood Canal summer-run ESU)",
    "CMHCS_Out": "Salmon, chum (Hood Canal summer-run ESU) - Outside range",
    "COCCA": "Salmon, coho (Central California Coast ESU)",
    "COCCA_Out": "Salmon, coho (Central California Coast ESU) - Outside range",
    "COLCR": "Salmon, coho (Lower Columbia River ESU)",
    "COLCR_Out": "Salmon, coho (Lower Columbia River ESU) - Outside range",
    "COORC": "Salmon, coho (Oregon Coast ESU)",
    "COORC_Out": "Salmon, coho (Oregon Coast ESU) - Outside range",
    "COSNC": "Salmon, coho (Southern Oregon/Northern California Coast ESU)",
    "COSNC_Out": "Salmon, coho (Southern Oregon/Northern California Coast ESU) - Outside range",
    "SOOZT": "Salmon, sockeye (Ozette Lake ESU)",
    "SOOZT_Out": "Salmon, sockeye (Ozette Lake ESU) - Outside range",
    "SOSNR": "Salmon, sockeye (Snake River ESU)",
    "SOSNR_Out": "Salmon, sockeye (Snake River ESU) - Outside range",
    "STCCC": "Steelhead (Central California Coast DPS)",
    "STCCC_Out": "Steelhead (Central California Coast DPS) - Outside range",
    "STCCV": "Steelhead (California Central Valley DPS)",
    "STCCV_Out": "Steelhead (California Central Valley DPS) - Outside range",
    "STLCR": "Steelhead (Lower Columbia River DPS)",
    "STLCR_Out": "Steelhead (Lower Columbia River DPS) - Outside range",
    "STMCR": "Steelhead (Middle Columbia River DPS)",
    "STMCR_Out": "Steelhead (Middle Columbia River DPS) - Outside range",
    "STMCX": "Steelhead (Middle Columbia River DPS--XN)",
    "STMCX_Out": "Steelhead (Middle Columbia River DPS--XN) - Outside range",
    "STNCA": "Steelhead (Northern California DPS)",
    "STNCA_Out": "Steelhead (Northern California DPS) - Outside range",
    "STPUG": "Steelhead (Puget Sound DPS)",
    "STPUG_Out": "Steelhead (Puget Sound DPS) - Outside range",
    "STSCA": "Steelhead (Southern California DPS)",
    "STSCA_Out": "Steelhead (Southern California DPS) - Outside range",
    "STSCC": "Steelhead (South-Central California Coast DPS)",
    "STSCC_Out": "Steelhead (South-Central California Coast DPS) - Outside range",
    "STSNR": "Steelhead (Snake River Basin DPS)",
    "STSNR_Out": "Steelhead (Snake River Basin DPS) - Outside range",
    "STUCR": "Steelhead (Upper Columbia River DPS)",
    "STUCR_Out": "Steelhead (Upper Columbia River DPS) - Outside range",
    "STUWR": "Steelhead (Upper Willamette River DPS)",
    "STUWR_Out": "Steelhead (Upper Willamette River DPS) - Outside range",
}

_LISTSTATUS = {
    "E": "Endangered",
    "T": "Threatened",
    "D": "Delisted",
    "S": "Species of Concern",
    "N": "Not Warranted",
}

_SCIENAME = {
    "1": "Oncorhynchus tshawytscha",
    "2": "Oncorhynchus nerka",
    "3": "Oncorhynchus mykiss",
    "4": "Oncorhynchus kisutch",
    "5": "Oncorhynchus keta",
}

_COMNAME = {
    "CK": "Salmon, Chinook",
    "CM": "Salmon, chum",
    "SO": "Salmon, sockeye",
    "CO": "Salmon, coho",
    "ST": "Steelhead",
}

_TAXON = {
    "1": "baleen whale",
    "2": "toothed whale",
    "3": "fish",
    "4": "pinniped",
    "5": "marine reptile",
    "6": "invertebrate",
    "7": "plant",
}

_LEADOFFICE = {
    "PIR": "Pacific Islands Region",
    "SER": "Southeast Region",
    "GAR": "Greater Atlantic Region",
    "WCR": "West Coast Region",
    "AKR": "Alaska Region",
    "OPR": "Office of Protected Resources",
}

_FEATURE_ACCESS = {
    "AC": "Accessible",
    "TH": "Trap and Haul",
    "AR": "Artificial",
    "NB": "Naturally Blocked",
    "AB": "Anthropogenically Blocked",
}

_SPECIES_SCI = {
    "CK": "Oncorhynchus tshawytscha",
    "SO": "Oncorhynchus nerka",
    "CO": "Oncorhynchus kisutch",
    "CM": "Oncorhynchus keta",
    "ST": "Oncorhynchus mykiss",
}

_RUN_TIMING = {
    "wi": "winter",
    "sp": "spring",
    "ss": "spring/summer",
    "su": "summer",
    "sw": "summer and winter",
    "fa": "fall",
    "lf": "late fall",
    "er": "early",
    "lt": "late",
    "el": "early and late",
    "xx": "unknown",
}

_POP_STATUS = {
    "EX": "Extant",
    "ET": "Extirpated",
    "FE": "Functionally Extirpated",
    "RE": "Reintroduced",
    "RJ": "Reintroduced - 10(j) Designation",
    "RC": "Recolonized",
}

_EXTINCTION_RISK = {
    "HR": "High Risk",
    "MR": "Moderate Risk",
    "LR": "Low Risk",
    "VI": "Viable",
    "HV": "Highly Viable",
    "DD": "Data Deficient",
    "MA": "Maintained",
}


def _decode(value: str, domain: Dict[str, str]) -> str:
    """Look up a coded value, returning the human-readable name or the raw value."""
    if not value:
        return ""
    return domain.get(str(value), value)


_OUT_FIELDS = (
    "listentity,liststatus,sciename,comname,taxon,leadoffice,"
    "frn,pubdate,effectdate,areasqkm,huc12,huc12_name,"
    "feature_access,notes,inporturl"
)

_LAYER1_OUT_FIELDS = (
    "dps,dps_id,species,listing_status,population,run_timing,status,"
    "extinction_risk,frn,hydrologic_huc_12,hydrologic_hu_12_name,"
    "hydrologic_hu_area_sqkm,hydrologic_hu_states,link_feature_access"
)


def get_esa_species_ranges_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """Return NOAA ESA-listed species ranges intersecting the ROI.

    Queries both complementary layers of the Ranges_dice FeatureServer:
    Layer 2 covers California and southern Oregon, while Layer 1 covers
    Washington, Idaho, Oregon, and transboundary fish ranges. Results are
    normalized and de-duplicated on (listed entity, HUC-12).

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with center, buffer_miles, total, species list,
        species_count, and watershed_count.
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
            "species": [],
            "species_count": 0,
            "watershed_count": 0,
            "error": str(e),
        }

    layer2_features, layer2_warnings = _query_layer(
        ESA_RANGES_LAYER_ID,
        _OUT_FIELDS,
        buffer_geom,
        "NOAA ESA species ranges Layer 2",
    )
    layer1_features, layer1_warnings = _query_layer(
        ESA_RANGES_FISH_LAYER_ID,
        _LAYER1_OUT_FIELDS,
        buffer_geom,
        "NOAA ESA fish ranges Layer 1",
    )

    species = _merge_ranges(
        _deduplicate_ranges(layer2_features),
        _normalize_layer1(layer1_features),
    )
    warnings = layer2_warnings + layer1_warnings
    unique_entities = {s["listed_entity"] for s in species}
    unique_hucs = {s["huc12"] for s in species if s.get("huc12")}

    result = {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(species),
        "species": species,
        "species_count": len(unique_entities),
        "watershed_count": len(unique_hucs),
        "warnings": warnings,
    }
    return add_empty_result_coverage_warning(
        result,
        buffer_geom,
        bounds=NOAA_WEST_COAST_EXPECTED_BOUNDS,
        dataset_name="NOAA Fisheries West Coast ESA ranges",
    )


def format_esa_species_ranges_summary(result: Dict) -> str:
    center = result["center"]
    species = result.get("species", [])
    lines = [
        "## NOAA ESA Species Ranges — Section 7 Screening",
        "",
        f"**Location:** ({center['latitude']}, {center['longitude']})",
        f"**Buffer:** {result['buffer_miles']} miles",
        f"**Range records:** {result['total']}",
        f"**Unique listed entities:** {result.get('species_count', 0)}",
        f"**HUC-12 watersheds:** {result.get('watershed_count', 0)}",
        "",
    ]

    if result.get("error"):
        lines += [f"> Warning: {result['error']}", ""]

    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]
    if result.get("coverage_warning"):
        lines += [f"> Warning: {result['coverage_warning']}", ""]

    if not species:
        lines += [
            "No NOAA ESA-listed species ranges found within the ROI.",
            "",
            "> **Note:** This service covers NOAA Fisheries West Coast Region",
            "> salmon and steelhead range records. Outside that service geography,",
            "> no records may mean the location is out-of-scope rather than no ESA concern.",
        ]
    else:
        by_entity: Dict[str, List[Dict]] = {}
        for s in species:
            entity = s.get("listed_entity") or "Unknown"
            by_entity.setdefault(entity, []).append(s)

        for entity, records in sorted(by_entity.items()):
            first = records[0]
            status = first.get("listing_status", "")
            sci = first.get("scientific_name", "")
            taxon = first.get("taxon", "")
            total_area = sum(r.get("area_sqkm") or 0 for r in records)
            lines += [
                f"### {entity} (*{sci}*) — {status}",
                f"Taxon: {taxon} | Watersheds: {len(records)}"
                + (f" | Total area: {total_area:,.1f} sq km" if total_area else ""),
                "",
            ]
            for r in sorted(records, key=lambda x: x.get("huc12_name", "")):
                huc_name = r.get("huc12_name") or "Unknown"
                huc = r.get("huc12") or ""
                area = f" — {r['area_sqkm']:,.1f} sq km" if r.get("area_sqkm") else ""
                access = f" [{r['feature_access']}]" if r.get("feature_access") else ""
                lines.append(f"- **{huc_name}** ({huc}){access}{area}")
            lines.append("")

        lines += [
            "---",
            "> **ESA Section 7 Note:** Federal actions within ESA-listed species ranges",
            "> may require consultation with NOAA Fisheries under Section 7 of the",
            "> Endangered Species Act (16 U.S.C. 1536).",
        ]

    return "\n".join(lines)


def _deduplicate_ranges(features: List[Dict]) -> List[Dict]:
    """Deduplicate diced range fragments by (listentity, huc12), summing area."""
    grouped: Dict[tuple, Dict] = {}

    for f in features:
        a = f.get("attributes", {})
        key = (a.get("listentity", ""), a.get("huc12", ""))

        if key not in grouped:
            grouped[key] = {
                "listed_entity": _decode(a.get("listentity") or "", _LISTENTITY),
                "listed_entity_code": a.get("listentity") or "",
                "listing_status": _decode(a.get("liststatus") or "", _LISTSTATUS),
                "scientific_name": _decode(a.get("sciename") or "", _SCIENAME),
                "common_name": _decode(a.get("comname") or "", _COMNAME),
                "taxon": _decode(a.get("taxon") or "", _TAXON),
                "lead_office": _decode(a.get("leadoffice") or "", _LEADOFFICE),
                "federal_register": a.get("frn") or "",
                "pub_date": a.get("pubdate") or "",
                "effective_date": a.get("effectdate") or "",
                "area_sqkm": 0.0,
                "huc12": a.get("huc12") or "",
                "huc12_name": a.get("huc12_name") or "",
                "feature_access": _decode(a.get("feature_access") or "", _FEATURE_ACCESS),
                "notes": a.get("notes") or "",
                "inport_url": a.get("inporturl") or "",
                "run_timing": "",
                "population": "",
                "population_status": "",
                "extinction_risk": "",
            }

        grouped[key]["area_sqkm"] += a.get("areasqkm") or 0.0

    result = []
    for entry in grouped.values():
        entry["area_sqkm"] = round(entry["area_sqkm"], 2) if entry["area_sqkm"] else None
        result.append(entry)

    return sorted(result, key=lambda x: (x["listed_entity"], x.get("huc12_name", "")))


def _query_layer(
    layer_id: int,
    out_fields: str,
    geometry: Dict,
    service_name: str,
) -> tuple[List[Dict], List[str]]:
    """Query one Ranges_dice layer while allowing the other layer to succeed."""
    try:
        result = ArcGISService.query_features(
            ESA_RANGES_SERVICE_URL,
            layer_id,
            geometry,
            out_fields=out_fields,
            timeout=30,
            service_name=service_name,
        )
        return result.features, result.warnings
    except Exception as exc:
        warning = f"{service_name} query failed: {exc}"
        logger.warning(warning)
        return [], [warning]


def _normalize_layer1(features: List[Dict]) -> List[Dict]:
    """Map Layer 1 fish records onto the Layer 2 range-record shape."""
    grouped: Dict[tuple, Dict] = {}

    for feature in features:
        attributes = feature.get("attributes", {})
        dps_id = attributes.get("dps_id") or ""
        listed_entity = attributes.get("dps") or _decode(dps_id, _LISTENTITY)
        huc12 = attributes.get("hydrologic_huc_12") or ""
        key = (listed_entity, huc12)

        if key not in grouped:
            species_code = attributes.get("species") or ""
            grouped[key] = {
                "listed_entity": listed_entity,
                "listed_entity_code": dps_id,
                "listing_status": _decode(attributes.get("listing_status") or "", _LISTSTATUS),
                "scientific_name": _decode(species_code, _SPECIES_SCI),
                "common_name": _decode(species_code, _COMNAME),
                "taxon": "fish",
                "lead_office": "West Coast Region",
                "federal_register": attributes.get("frn") or "",
                "pub_date": "",
                "effective_date": "",
                "area_sqkm": 0.0,
                "huc12": huc12,
                "huc12_name": attributes.get("hydrologic_hu_12_name") or "",
                "feature_access": _decode(
                    attributes.get("link_feature_access") or "",
                    _FEATURE_ACCESS,
                ),
                "notes": "",
                "inport_url": "",
                "run_timing": _decode(attributes.get("run_timing") or "", _RUN_TIMING),
                "population": attributes.get("population") or "",
                "population_status": _decode(attributes.get("status") or "", _POP_STATUS),
                "extinction_risk": _decode(
                    attributes.get("extinction_risk") or "",
                    _EXTINCTION_RISK,
                ),
            }

        grouped[key]["area_sqkm"] += attributes.get("hydrologic_hu_area_sqkm") or 0.0

    normalized = []
    for entry in grouped.values():
        entry["area_sqkm"] = round(entry["area_sqkm"], 2) if entry["area_sqkm"] else None
        normalized.append(entry)
    return normalized


def _merge_ranges(layer2: List[Dict], layer1: List[Dict]) -> List[Dict]:
    """Merge complementary range layers, preferring Layer 2 on collisions."""
    merged: Dict[tuple, Dict] = {}
    for entry in layer1 + layer2:
        merged[(entry["listed_entity"], entry.get("huc12", ""))] = entry
    return sorted(
        merged.values(),
        key=lambda entry: (entry["listed_entity"], entry.get("huc12_name", "")),
    )
