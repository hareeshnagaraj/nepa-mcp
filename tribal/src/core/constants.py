"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# UNIT CONVERSIONS
# =============================================================================

# Square meters to square miles conversion factor
SQ_METERS_TO_SQ_MILES = 2589988.11


# =============================================================================
# CENSUS TIGERWEB SERVICES
# =============================================================================

# American Indian/Alaska Native/Native Hawaiian Areas (AIANNHA) service
TIGERWEB_AIANNHA_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/AIANNHA/MapServer"

# Tribal land layer IDs and names
# Layer IDs map to specific tribal land categories in the AIANNHA service
TRIBAL_LAYERS = {
    0: "Alaska Native Regional Corporations",
    1: "Tribal Subdivisions",
    2: "Federal American Indian Reservations",
    3: "Off-Reservation Trust Lands",
    4: "State American Indian Reservations",
    5: "Hawaiian Home Lands",
}
