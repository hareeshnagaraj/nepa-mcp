"""
NEPA Assist EPA API Integration
Provides environmental screening for NEPA compliance using EPA's NEPAssist tool

"""

import requests
from typing import Dict
import re
from bs4 import BeautifulSoup
from nepa_mcp_common.arcgis import ArcGISService


def create_roi_polygon_coords(lat: float, lon: float, buffer_miles: float) -> str:
    """
    Create polygon coordinates for NEPA Assist API from center point and buffer
    Returns comma-separated coordinate string in lat,lon format (API requirement)

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        buffer_miles: Buffer radius in miles

    Returns:
        Comma-separated coordinate string: "lat1,lon1,lat2,lon2,..."

    Note: NEPA Assist has URL length limits, so we use a simplified bounding box
    """
    # Get buffer geometry
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

    # Extract polygon rings from ESRI JSON geometry
    if "rings" not in buffer_geom or not buffer_geom["rings"]:
        raise ValueError("Buffer geometry does not contain valid polygon rings")

    # Get the outer ring (first ring)
    outer_ring = buffer_geom["rings"][0]

    # Calculate bounding box from the polygon (NEPA Assist has URL length limits)
    # Extract all lons and lats
    lons = [coord[0] for coord in outer_ring]
    lats = [coord[1] for coord in outer_ring]

    # Get extent
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # Create simple 5-point polygon (bounding box)
    # Format: NW, NE, SE, SW, NW (close polygon)
    bbox_coords = [
        (max_lat, min_lon),  # NW
        (max_lat, max_lon),  # NE
        (min_lat, max_lon),  # SE
        (min_lat, min_lon),  # SW
        (max_lat, min_lon),  # NW (close)
    ]

    # Convert to NEPA Assist format: lon,lat,lon,lat,... (NOT lat,lon!)
    # EPA NEPA Assist expects coordinates in longitude,latitude order
    coord_string = ",".join([f"{lon},{lat}" for lat, lon in bbox_coords])

    return coord_string


def query_nepa_assist(lat: float, lon: float, buffer_miles: float = 0, project_title: str = "") -> Dict:
    """
    Query EPA NEPAssist API for environmental screening

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        buffer_miles: Buffer distance in miles (default 0)
        project_title: Optional project title

    Returns:
        Dictionary containing environmental screening results
    """
    # Create polygon coordinates
    coords = create_roi_polygon_coords(lat, lon, buffer_miles)

    # Build API URL
    base_url = "https://nepassisttool.epa.gov/nepassist/analysis.aspx"

    # IMPORTANT: The radius parameter tells EPA to check "within X miles of" the polygon
    # Without it, the API only checks if features are contained within the polygon itself
    params = {
        "ptitle": project_title,
        "coords": coords,
        "type": "polygon",
        "radius": "1",  # Always use 1-mile proximity buffer (standard NEPA practice)
        "unit": "miles",
        "f": "report",
    }

    # Make request
    response = requests.get(base_url, params=params, timeout=60)
    response.raise_for_status()

    # Parse HTML response
    soup = BeautifulSoup(response.text, "html.parser")

    # Extract results
    results = parse_nepa_assist_results(soup)

    # Add metadata
    results["metadata"] = {
        "latitude": lat,
        "longitude": lon,
        "buffer_miles": buffer_miles,
        "project_title": project_title,
        "api_url": response.url,
    }

    return results


def parse_nepa_assist_results(soup: BeautifulSoup) -> Dict:
    """
    Parse NEPA Assist HTML response into structured data
    """
    results = {
        "air_quality": {},
        "water_resources": {},
        "contaminated_sites": {},
        "community_features": {},
        "natural_resources": {},
        "cultural_resources": {},
        "summary": {"total_checks": 0, "yes_count": 0, "no_count": 0, "flagged_issues": []},
    }

    # Find all question rows in the table
    # Classes are like: yes0, yes1, no0, no1, wetCell
    rows = soup.find_all("tr", class_=re.compile(r"^(yes|no)\d"))

    for row in rows:
        question_td = row.find("td", class_="questionText")
        answer_td = row.find_all("td")[1] if len(row.find_all("td")) > 1 else None

        if not question_td or not answer_td:
            continue

        # Extract question text
        question_link = question_td.find("a")
        if not question_link:
            continue

        question_text = question_link.get_text(strip=True)

        # Extract answer
        answer_link = answer_td.find("a")
        if answer_link:
            answer = answer_link.get_text(strip=True).lower()
        else:
            answer = answer_td.get_text(strip=True).lower()

        # Categorize and store
        categorize_result(results, question_text, answer)

        # Update summary
        results["summary"]["total_checks"] += 1
        if answer == "yes":
            results["summary"]["yes_count"] += 1
            results["summary"]["flagged_issues"].append(question_text)
        elif answer == "no":
            results["summary"]["no_count"] += 1

    return results


def categorize_result(results: Dict, question: str, answer: str):
    """
    Categorize NEPA Assist results into logical groups
    """
    question_lower = question.lower()

    # Air Quality
    if any(
        term in question_lower
        for term in [
            "ozone",
            "lead",
            "so2",
            "pm2.5",
            "pm10",
            "co ",
            "no2",
            "air emission",
            "non-attainment",
            "maintenance area",
        ]
    ):
        results["air_quality"][question] = answer

    # Water Resources
    elif any(
        term in question_lower for term in ["stream", "waterbody", "wetland", "water discharger", "npdes", "impaired"]
    ):
        results["water_resources"][question] = answer

    # Contaminated Sites
    elif any(
        term in question_lower
        for term in ["brownfield", "superfund", "tri", "toxic release", "hazardous waste", "rcra"]
    ):
        results["contaminated_sites"][question] = answer

    # Community Features
    elif any(term in question_lower for term in ["school", "airport", "hospital", "federal land"]):
        results["community_features"][question] = answer

    # Natural Resources
    elif any(
        term in question_lower
        for term in [
            "aquifer",
            "essential fish habitat",
            "efh",
            "hapc",
            "critical habitat",
            "critical environmental concern",
            "mitigation bank",
            "conservation bank",
            "in-lieu-fee",
        ]
    ):
        results["natural_resources"][question] = answer

    # Cultural Resources
    elif any(term in question_lower for term in ["historic", "nrhp", "tribal", "land cession"]):
        results["cultural_resources"][question] = answer

    # Other
    else:
        if "other" not in results:
            results["other"] = {}
        results["other"][question] = answer


def format_nepa_assist_report(results: Dict) -> str:
    """
    Format NEPA Assist results into a readable report
    """
    metadata = results["metadata"]
    summary = results["summary"]

    report = f"""
EPA NEPA ASSIST ENVIRONMENTAL SCREENING REPORT

Location: ({metadata["latitude"]}, {metadata["longitude"]})
Buffer: {metadata["buffer_miles"]} miles
Project: {metadata["project_title"] if metadata["project_title"] else "N/A"}

===================================================================

EXECUTIVE SUMMARY

Total Environmental Checks: {summary["total_checks"]}
Flagged Issues (YES): {summary["yes_count"]}
No Issues Found (NO): {summary["no_count"]}

"""

    if summary["flagged_issues"]:
        report += "\n[!] FLAGGED ENVIRONMENTAL CONCERNS:\n"
        for i, issue in enumerate(summary["flagged_issues"], 1):
            report += f"  {i}. {issue}\n"
        report += "\n"
    else:
        report += "[OK] No major environmental concerns flagged in screening.\n\n"

    report += "===================================================================\n\n"

    # Air Quality
    if results["air_quality"]:
        report += "AIR QUALITY\n"
        report += format_category(results["air_quality"])
        report += "\n"

    # Water Resources
    if results["water_resources"]:
        report += "WATER RESOURCES\n"
        report += format_category(results["water_resources"])
        report += "\n"

    # Contaminated Sites
    if results["contaminated_sites"]:
        report += "CONTAMINATED SITES\n"
        report += format_category(results["contaminated_sites"])
        report += "\n"

    # Community Features
    if results["community_features"]:
        report += "COMMUNITY FEATURES\n"
        report += format_category(results["community_features"])
        report += "\n"

    # Natural Resources
    if results["natural_resources"]:
        report += "NATURAL RESOURCES\n"
        report += format_category(results["natural_resources"])
        report += "\n"

    # Cultural Resources
    if results["cultural_resources"]:
        report += "CULTURAL RESOURCES\n"
        report += format_category(results["cultural_resources"])
        report += "\n"

    # Other
    if "other" in results and results["other"]:
        report += "OTHER ENVIRONMENTAL FACTORS\n"
        report += format_category(results["other"])
        report += "\n"

    report += "===================================================================\n\n"
    report += "NEPA COMPLIANCE GUIDANCE\n\n"
    report += generate_compliance_guidance(results)

    return report


def format_category(category_dict: Dict) -> str:
    """Format a category dictionary into readable text"""
    output = ""
    for question, answer in category_dict.items():
        symbol = "[!] YES" if answer == "yes" else "[OK] NO"
        output += f"  {symbol} - {question}\n"
    return output


def generate_compliance_guidance(results: Dict) -> str:
    """Generate NEPA compliance guidance based on screening results"""
    guidance = []

    # Air Quality
    if any("yes" in v for v in results["air_quality"].values()):
        guidance.append("""
AIR QUALITY COMPLIANCE:
- Coordinate with EPA Region and State Air Quality Agency
- Obtain Clean Air Act General Conformity determination if in non-attainment area
- Evaluate impacts on National Ambient Air Quality Standards (NAAQS)
- Consider air quality modeling for emissions sources
""")

    # Water Resources
    if any("yes" in v for v in results["water_resources"].values()):
        guidance.append("""
WATER RESOURCES COMPLIANCE:
- Section 404 Clean Water Act permit may be required for wetland impacts
- NPDES permit coordination if discharges to waters of the U.S.
- Section 401 Water Quality Certification from state
- Consult with U.S. Army Corps of Engineers for jurisdictional determination
- Coordinate with EPA for impaired waters (303(d) list) considerations
""")

    # Contaminated Sites
    if any("yes" in v for v in results["contaminated_sites"].values()):
        guidance.append("""
CONTAMINATED SITES COMPLIANCE:
- Phase I/II Environmental Site Assessment may be required
- Coordination with EPA Superfund or Brownfields programs
- State hazardous waste agency notification
- Consider vapor intrusion and soil contamination risks
""")

    # Natural Resources
    if any("yes" in v for v in results["natural_resources"].values()):
        guidance.append("""
NATURAL RESOURCES COMPLIANCE:
- ESA Section 7 consultation if critical habitat present
- Essential Fish Habitat (EFH) consultation under Magnuson-Stevens Act
- Coordinate with NOAA Fisheries and/or USFWS
- Evaluate use of mitigation/conservation banking
""")

    # Cultural Resources
    if any("yes" in v for v in results["cultural_resources"].values()):
        guidance.append("""
CULTURAL RESOURCES COMPLIANCE:
- Section 106 NHPA consultation with State Historic Preservation Office (SHPO)
- Tribal consultation under Executive Order 13175
- Archaeological and historical surveys may be required
- Government-to-government consultation for tribal lands
""")

    if not guidance:
        guidance.append("""
GENERAL NEPA COMPLIANCE:
Based on this screening, no major environmental concerns were flagged.
However, standard NEPA analysis should include:
- Evaluation of cumulative impacts
- Assessment of reasonable alternatives
- Public involvement and scoping
- Interagency coordination as appropriate
""")

    return "\n".join(guidance)
