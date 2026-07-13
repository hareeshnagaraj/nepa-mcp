#!/usr/bin/env python3
"""
Census API Client - Coordinate-based queries for NEPA analysis.

Provides socioeconomic data from the American Community Survey (ACS) for
counties intersecting a Region of Interest (ROI) buffer.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from nepa_mcp_common.arcgis import ArcGISService
from src.core.fips_utils import STATE_FIPS_TO_ABBR

logger = logging.getLogger(__name__)

# Constants
INVALID_VALUES = {"-888888888", "null", ""}
EXCLUDED_INDUSTRY_KEYWORDS = {"TOTAL", "ALL", "NOT CLASSIFIED"}


class CensusError(Exception):
    """Exception for Census API errors."""

    pass


# Metrics: variable_code -> (label, format_type)
# format_type: 'currency', 'percentage', 'count'
METRICS = {
    "DP03_0062E": ("Median household income", "currency"),
    "DP03_0088E": ("Per capita income", "currency"),
    "DP03_0128PE": ("Families below poverty level", "percentage"),
    "DP03_0134PE": ("People below poverty level", "percentage"),
    "DP03_0009PE": ("Unemployment rate", "percentage"),
    "DP03_0008E": ("Civilian labor force", "count"),
    "DP03_0004E": ("Employed", "count"),
}


class SimplifiedCensusAPI:
    """Census API client for coordinate-based queries."""

    BASE_URL = "https://api.census.gov/data/{year}/acs/acs5/profile"
    TIGERWEB_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
    TIGERWEB_COUNTY_LAYER = 82
    DEFAULT_YEAR = 2023
    REQUEST_TIMEOUT = 30
    ACS_SPAN = 4

    # Class-level caches
    _variables_cache: Dict[str, Dict[str, dict]] = {}
    _industry_vars_cache: Dict[str, List[Tuple[str, str]]] = {}
    _occupation_vars_cache: Dict[str, List[Tuple[str, str]]] = {}

    def __init__(self, api_key: Optional[str] = None, year: int = DEFAULT_YEAR):
        self.year = year
        self.api_key = api_key or os.getenv("CENSUS_API_KEY")
        if not self.api_key:
            raise CensusError(
                "No Census API key. Set CENSUS_API_KEY env var or pass api_key. "
                "Get one at: https://api.census.gov/data/key_signup.html"
            )

    def _get_counties(self, lat: float, lon: float, buffer_miles: float) -> List[Dict]:
        """Get counties intersecting ROI buffer via TIGERweb."""
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
        simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geom)

        url = f"{self.TIGERWEB_URL}/{self.TIGERWEB_COUNTY_LAYER}/query"
        params = {
            "geometry": json.dumps(simplified_geom),
            "geometryType": "esriGeometryPolygon",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": False,
            "outFields": "NAME,GEOID",
            "f": "json",
        }

        try:
            resp = requests.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise CensusError(f"TIGERweb lookup failed: {e}")

        counties = []
        for feat in data.get("features", []):
            attrs = feat.get("attributes", {})
            geoid = attrs.get("GEOID", "")
            if len(geoid) >= 5:
                counties.append(
                    {
                        "name": attrs.get("NAME", "Unknown"),
                        "geoid": geoid,
                        "state_fips": geoid[:2],
                        "county_fips": geoid[2:],
                        "state_abbr": STATE_FIPS_TO_ABBR.get(geoid[:2], ""),
                    }
                )
        return sorted(counties, key=lambda x: (x["state_fips"], x["name"]))

    def _fetch_census_data(self, county: Dict, variables: List[str]) -> Dict[str, Any]:
        """Fetch Census data for a county. Returns {variable: value}."""
        url = self.BASE_URL.format(year=self.year)
        params = {
            "get": ",".join(variables),
            "for": f"county:{county['county_fips']}",
            "in": f"state:{county['state_fips']}",
            "key": self.api_key,
        }

        try:
            resp = requests.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if len(data) < 2:
                return {}
            headers, values = data[0], data[1]
            return {var: values[headers.index(var)] for var in variables if var in headers}
        except (requests.RequestException, ValueError, IndexError):
            return {}

    def _format_value(self, raw: Optional[str], fmt: str) -> str:
        """Format a Census value for display."""
        if not raw or raw in INVALID_VALUES:
            return "N/A"
        try:
            val = float(raw)
            if fmt == "currency":
                return f"${val:,.0f}"
            elif fmt == "percentage":
                return f"{val:.1f}%"
            elif fmt == "count":
                return f"{val:,.0f}"
            return str(val)
        except (ValueError, TypeError):
            return "N/A"

    def _get_industry_occupation_vars(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """Get and cache industry/occupation variable lists."""
        year_key = str(self.year)

        # Return cached if available
        if year_key in self._industry_vars_cache:
            return self._industry_vars_cache[year_key], self._occupation_vars_cache[year_key]

        # Fetch variables metadata
        if year_key not in self._variables_cache:
            url = f"https://api.census.gov/data/{self.year}/acs/acs5/profile/variables.json"
            try:
                resp = requests.get(url, timeout=self.REQUEST_TIMEOUT)
                resp.raise_for_status()
                self._variables_cache[year_key] = resp.json().get("variables", {})
            except Exception:
                self._variables_cache[year_key] = {}

        variables = self._variables_cache[year_key]
        industry_vars, occupation_vars = [], []

        for var, meta in variables.items():
            if not var.endswith("PE"):
                continue
            label = str(meta.get("label", ""))
            label_upper = label.upper()

            if "INDUSTRY" in label_upper and "CLASS OF WORKER" not in label_upper:
                clean = self._clean_label(label)
                industry_vars.append((var, clean))
            elif "OCCUPATION" in label_upper and "INDUSTRY" not in label_upper:
                clean = self._clean_label(label)
                occupation_vars.append((var, clean))

        self._industry_vars_cache[year_key] = industry_vars
        self._occupation_vars_cache[year_key] = occupation_vars
        return industry_vars, occupation_vars

    def _clean_label(self, label: str) -> str:
        """Clean ACS variable label for display."""
        cleaned = re.sub(r"^(Estimate|Percent)!!", "", label, flags=re.IGNORECASE)
        cleaned = re.sub(r"^.*?(OCCUPATION|INDUSTRY)!!", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^Civilian employed population 16 years and over!!", "", cleaned, flags=re.IGNORECASE)
        if "!!" in cleaned:
            cleaned = cleaned.split("!!")[-1]
        return cleaned.strip()

    def _pick_top_n(self, raw_data: Dict, var_list: List[Tuple[str, str]], top_n: int) -> List[Dict]:
        """Pick top N categories by percentage value."""
        items = []
        for var, label in var_list:
            raw = raw_data.get(var)
            if raw and raw not in INVALID_VALUES:
                try:
                    val = float(raw)
                    if 0.1 <= val <= 100 and not any(kw in label.upper() for kw in EXCLUDED_INDUSTRY_KEYWORDS):
                        items.append((label, val))
                except (ValueError, TypeError):
                    pass
        items.sort(key=lambda x: x[1], reverse=True)
        return [{"category": lbl, "percent": f"{val:.1f}"} for lbl, val in items[:top_n]]

    def get_census_data_by_coordinates(
        self,
        lat: float,
        lon: float,
        buffer_miles: float = 25.0,
        include_industries: bool = False,
        top_n: int = 2,
    ) -> Dict[str, Any]:
        """
        Get Census data for all counties intersecting an ROI.

        Args:
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            buffer_miles: Buffer radius in miles
            include_industries: Include top industries/occupations
            top_n: Number of top industries/occupations per county

        Returns:
            Dictionary with center, buffer_miles, acs_period, counties list
        """
        period = f"{self.year - self.ACS_SPAN}-{self.year}"
        base_result = {
            "center": {"latitude": lat, "longitude": lon},
            "buffer_miles": buffer_miles,
            "acs_period": period,
        }

        # Get counties in ROI
        try:
            counties = self._get_counties(lat, lon, buffer_miles)
        except CensusError as e:
            logger.error(f"County lookup failed: {e}")
            return {**base_result, "total_counties": 0, "counties": [], "status": "error", "error_message": str(e)}

        if not counties:
            return {**base_result, "total_counties": 0, "counties": [], "status": "success"}

        # Prepare variables to fetch
        all_vars = list(METRICS.keys())
        industry_vars, occupation_vars = [], []
        if include_industries:
            industry_vars, occupation_vars = self._get_industry_occupation_vars()
            all_vars = list(set(all_vars + [v for v, _ in industry_vars] + [v for v, _ in occupation_vars]))

        # Fetch data for each county (single API call per county)
        county_results = []
        for county in counties:
            raw_data = self._fetch_census_data(county, all_vars)

            if not raw_data:
                county_results.append(
                    {
                        "name": county["name"],
                        "state": county["state_abbr"],
                        "fips": county["geoid"],
                        "indicators": {},
                        "status": "error",
                        "error_message": "No data returned",
                    }
                )
                continue

            # Format metrics
            indicators = {}
            for var, (label, fmt) in METRICS.items():
                indicators[label] = self._format_value(raw_data.get(var), fmt)

            entry = {
                "name": county["name"],
                "state": county["state_abbr"],
                "fips": county["geoid"],
                "indicators": indicators,
                "status": "success",
            }

            # Add industries/occupations if requested
            if include_industries:
                entry["industries"] = self._pick_top_n(raw_data, industry_vars, top_n)
                entry["occupations"] = self._pick_top_n(raw_data, occupation_vars, top_n)

            county_results.append(entry)

        return {**base_result, "total_counties": len(county_results), "counties": county_results, "status": "success"}


def format_census_summary(census_data: Dict[str, Any]) -> str:
    """Format Census data into human-readable summary."""
    center = census_data.get("center", {})
    lat, lon = center.get("latitude", 0), center.get("longitude", 0)
    buffer = census_data.get("buffer_miles", 0)
    period = census_data.get("acs_period", "N/A")
    counties = census_data.get("counties", [])

    lines = [
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        f"ACS Period: {period}",
        f"Total Counties: {len(counties)}",
        "",
    ]

    if not counties:
        lines.append("No counties found in the region of interest.")
    else:
        lines.append("Socioeconomic Indicators by County:")
        lines.append("")

        for county in counties:
            lines.append(f"  {county.get('name', 'Unknown')}, {county.get('state', '')}")

            if county.get("status") != "success":
                lines.append(f"    Error: {county.get('error_message', 'Unknown error')}")
                lines.append("")
                continue

            # Indicators
            for label, value in county.get("indicators", {}).items():
                lines.append(f"    {label}: {value}")

            # Industries
            for ind in county.get("industries", []):
                lines.append(f"    Top Industry: {ind['category']} ({ind['percent']}%)")

            # Occupations
            for occ in county.get("occupations", []):
                lines.append(f"    Top Occupation: {occ['category']} ({occ['percent']}%)")

            lines.append("")

    lines.append("Data Source: U.S. Census Bureau ACS 5-Year Estimates")
    return "\n".join(lines)
