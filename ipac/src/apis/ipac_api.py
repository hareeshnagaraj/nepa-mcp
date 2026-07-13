"""
USFWS IPaC (Information for Planning and Consultation) API Integration.

This module provides access to the USFWS IPaC API for threatened/endangered species
and other Fish & Wildlife Service resources within a Region of Interest.

API Documentation: https://ipac.ecosphere.fws.gov/
"""

from __future__ import annotations

import json
import requests
from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService


def get_ipac_resources_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query the IPaC API for threatened/endangered species and other FWS resources.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary mirroring the IPaC API response with additional summary stats.
    """
    return _query_ipac_api(lat, lon, buffer_miles)


def _query_ipac_api(lat: float, lon: float, buffer_miles: float) -> Dict:
    """
    Query USFWS IPaC (Information for Planning and Consultation) API
    for threatened/endangered species and other FWS resources in ROI.

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        buffer_miles: Buffer distance in miles

    Returns:
        Dictionary containing resource lists and explicit `*_count` fields:
        - species / species_count
        - migratory_birds / migbirds_count
        - wetlands / wetlands_count
        - refuges / refuges_count
        - field_offices
        - critical_habitat / critical_habitat_count
    """
    try:
        # Step 1: Get ROI polygon geometry
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

        # Simplify polygon to reduce payload size
        simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geom)

        # Extract just the polygon coordinates (IPaC wants pure GeoJSON geometry)
        polygon_geometry = {"type": "Polygon", "coordinates": simplified_geom["rings"]}

        # Step 2: Build IPaC request
        ipac_request = {
            "location.footprint": json.dumps(polygon_geometry),
            "timeout": 45,
            "apiVersion": "1.0.0",
            "locationFormat": "GeoJSON",
            "includeOtherFwsResources": True,
            "includeCrithabGeometry": False,  # Don't include geometry (too large)
            "saveLocationForProjectCreation": False,
        }

        # Step 3: POST to IPaC API
        ipac_url = "https://ipac.ecosphere.fws.gov/location/api/resources"
        response = requests.post(
            ipac_url,
            json=ipac_request,
            headers={"Content-Type": "application/json"},
            timeout=55,
        )

        response.raise_for_status()
        data = response.json()

        resources = data.get("resources")
        if not isinstance(resources, dict):
            raise ValueError("IPaC response did not include a resources object")

        # Step 4: Parse and structure the response
        species_list = []
        populations = resources.get("populationsBySid", {})

        for pop_id, pop_data in populations.items():
            pop = pop_data.get("population", {})
            species_list.append(
                {
                    "id": pop.get("sid", {}).get("val", pop_id),
                    "common_name": pop.get("optionalCommonName", ""),
                    "scientific_name": pop.get("optionalScientificName", ""),
                    "short_name": pop.get("shortName", ""),
                    "listing_status": pop.get("listingStatusName", ""),
                    "listing_code": pop.get("listingStatusCode", ""),
                    "critical_habitat": pop.get("criticalHabitat", "None"),
                }
            )

        # Sort by common name
        species_list.sort(key=lambda x: x["common_name"])

        # Migratory birds - parse phenology data
        migbirds_list = []
        for bird in resources.get("migbirds", []):
            phenology = bird.get("phenologySpecies", {})
            migbirds_list.append(
                {
                    "common_name": phenology.get("commonName", ""),
                    "scientific_name": phenology.get("scientificName", ""),
                    "code": phenology.get("code", ""),
                    "conservation_level": bird.get("level", {}).get("name", ""),
                    "bcc": bird.get("bcc", False),
                    "breeds_from": bird.get("optionalBreedsFrom", ""),
                    "breeds_to": bird.get("optionalBreedsTo", ""),
                }
            )

        # Sort by common name
        migbirds_list.sort(key=lambda x: x["common_name"])

        # Wetlands - extract items from dict
        wetlands_data = resources.get("wetlands", {})
        wetlands_items = []
        if isinstance(wetlands_data, dict):
            wetlands_items = wetlands_data.get("items", [])
            # Parse wetland details
            wetlands_list = []
            for wetland in wetlands_items:
                attrs = wetland.get("attributes", {})
                wetlands_list.append(
                    {
                        "code": wetland.get("wetlandCode", ""),
                        "system": attrs.get("SYSTEM_NAME", ""),
                        "class": attrs.get("CLASS_NAME", ""),
                        "water_regime": attrs.get("WATER_REGIME_SUBGROUP", ""),
                        "shape": attrs.get("Shape", ""),
                    }
                )
        else:
            wetlands_list = []

        # Refuges - extract items from dict
        refuges_data = resources.get("refuges", {})
        refuges_list = []
        if isinstance(refuges_data, dict):
            refuges_items = refuges_data.get("items", [])
            for refuge in refuges_items:
                refuges_list.append(
                    {
                        "name": refuge.get("name", ""),
                        "type": refuge.get("rslType", ""),
                        "acres": refuge.get("acres", 0),
                        "org_code": refuge.get("orgCode", ""),
                    }
                )

        # Field offices
        field_offices = []
        for office in resources.get("fieldOffices", []):
            field_offices.append({"name": office.get("officeName", ""), "code": office.get("officeCode", "")})

        # Critical Habitat - parse and cross-reference with species data
        critical_habitat_list = []
        crithabs = resources.get("crithabs", [])

        for crithab in crithabs:
            pop_sid = crithab.get("populationSid", {})
            pop_id = pop_sid.get("val", "")

            # Find matching species for detailed info
            species_name = "Unknown"
            scientific_name = ""
            listing_status = ""
            fr_date = ""
            fr_type = ""
            fr_url = ""

            if pop_id in populations:
                pop_data = populations[pop_id]
                pop = pop_data.get("population", {})
                species_name = pop.get("optionalCommonName", "Unknown")
                scientific_name = pop.get("optionalScientificName", "")
                listing_status = pop.get("listingStatusName", "")

                # Get Federal Register critical habitat designation info
                fr_info = pop_data.get("optionalFederalRegisterCrithabStatus", {})
                if fr_info:
                    fr_date = fr_info.get("date", "")
                    fr_type = fr_info.get("displayType", "")
                    fr_url = fr_info.get("url", "")

            critical_habitat_list.append(
                {
                    "species_id": pop_id,
                    "common_name": species_name,
                    "scientific_name": scientific_name,
                    "listing_status": listing_status,
                    "critical_habitat_type": crithab.get("type", ""),
                    "species_in_footprint": crithab.get("speciesInFootprint", False),
                    "has_geometry": crithab.get("hasGeometry", False),
                    "federal_register_date": fr_date,
                    "federal_register_type": fr_type,
                    "federal_register_url": fr_url,
                }
            )

        # Marine Mammals - cross-reference with population data
        marine_mammals_list = []
        marine_mammals = resources.get("marineMammals", [])
        all_populations = resources.get("allReferencedPopulationsBySid", {})

        for mm in marine_mammals:
            pop_sid = mm.get("populationSid", {})
            pop_id = pop_sid.get("val", "")

            # Try main populations first, then all referenced populations
            pop_data = populations.get(pop_id) or all_populations.get(pop_id)

            if pop_data:
                # Handle both formats (with or without 'population' wrapper)
                pop = pop_data.get("population", pop_data) if "population" in pop_data else pop_data

                marine_mammals_list.append(
                    {
                        "species_id": pop_id,
                        "common_name": pop.get("optionalCommonName", "Unknown"),
                        "scientific_name": pop.get("optionalScientificName", ""),
                        "listing_status": pop.get("listingStatusName", ""),
                        "listing_code": pop.get("listingStatusCode", ""),
                        "group": pop.get("groupName", "Mammals"),
                    }
                )

        # Fish Hatcheries - extract from facilities
        fish_hatcheries_list = []
        fish_hatcheries_data = resources.get("fishHatcheries", {})

        if isinstance(fish_hatcheries_data, dict):
            hatchery_items = fish_hatcheries_data.get("items", [])
            for hatchery in hatchery_items:
                fish_hatcheries_list.append(
                    {
                        "name": hatchery.get("name", ""),
                        "type": hatchery.get("rslType", ""),
                        "acres": hatchery.get("acres", 0),
                        "org_code": hatchery.get("orgCode", ""),
                        "url": hatchery.get("url", ""),
                    }
                )

        return {
            "center": {"latitude": lat, "longitude": lon},
            "buffer_miles": buffer_miles,
            "species": species_list,
            "species_count": len(species_list),
            "migratory_birds": migbirds_list,
            "migbirds_count": len(migbirds_list),
            "wetlands": wetlands_list,
            "wetlands_count": len(wetlands_list),
            "refuges": refuges_list,
            "refuges_count": len(refuges_list),
            "field_offices": field_offices,
            "critical_habitat": critical_habitat_list,
            "critical_habitat_count": len(critical_habitat_list),
            "marine_mammals": marine_mammals_list,
            "marine_mammals_count": len(marine_mammals_list),
            "fish_hatcheries": fish_hatcheries_list,
            "fish_hatcheries_count": len(fish_hatcheries_list),
            "coastal_barriers": resources.get("coastalBarriers", []),
            "raw_response": data,  # Include full response for advanced users
        }

    except requests.exceptions.RequestException as e:
        raise Exception(f"IPaC API request failed: {str(e)}")
    except (KeyError, ValueError) as e:
        raise Exception(f"Error parsing IPaC response: {str(e)}")


def format_ipac_summary(ipac_data: Dict) -> str:
    """
    Format IPaC data as a markdown summary.

    Args:
        ipac_data: Data from get_ipac_resources_in_roi()

    Returns:
        Formatted markdown string
    """
    center = ipac_data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = ipac_data.get("buffer_miles", 0)
    species_count = ipac_data.get("species_count", len(ipac_data.get("species", [])))
    migbirds_count = ipac_data.get("migbirds_count", len(ipac_data.get("migratory_birds", [])))
    wetlands_count = ipac_data.get("wetlands_count", len(ipac_data.get("wetlands", [])))
    critical_habitat_count = ipac_data.get("critical_habitat_count", len(ipac_data.get("critical_habitat", [])))

    lines = [
        "USFWS IPaC Resources within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        "",
        f"Threatened/Endangered Species: {species_count}",
        f"Migratory Birds: {migbirds_count}",
        f"Wetland Types: {wetlands_count}",
        f"Critical Habitat Units: {critical_habitat_count}",
        "",
    ]

    critical = ipac_data.get("critical_habitat", [])
    if critical:
        lines.append("Critical Habitat Designations:")
        for habitat in critical:
            lines.append(
                f"- {habitat['common_name']} ({habitat['listing_status']}) – {habitat.get('critical_habitat_type', 'Unknown')} "
                f"(FR: {habitat.get('federal_register_date', 'N/A')})"
            )
        lines.append("")

    species = ipac_data.get("species", [])
    if species:
        lines.append("Threatened & Endangered Species:")
        for sp in species:
            lines.append(f"- {sp['common_name']} ({sp['scientific_name']}) – {sp['listing_status']}")
        lines.append("")

    birds = ipac_data.get("migratory_birds", [])
    if birds:
        lines.append("Representative Migratory Birds:")
        for bird in birds[:10]:
            lines.append(f"- {bird['common_name']} ({bird['conservation_level']})")
        if len(birds) > 10:
            lines.append(f"... and {len(birds) - 10} additional species")
        lines.append("")

    lines.append(
        "Coordinate with the responsible USFWS field office for ESA Section 7 consultation and MBTA compliance."
    )

    return "\n".join(lines)
