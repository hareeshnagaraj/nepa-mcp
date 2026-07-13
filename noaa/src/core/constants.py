"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# NOAA WEST COAST REGION CRITICAL HABITAT
# =============================================================================

# NOAA Fisheries West Coast Region critical habitat FeatureServer (diced geometry)
NOAA_WCR_CH_SERVICE_URL = "https://maps.fisheries.noaa.gov/server/rest/services/Hosted/WCR_ch_dice/FeatureServer"

# Layer IDs within the WCR critical habitat FeatureServer
NOAA_WCR_CH_LAYERS = {
    1: "Critical Habitat (Lines)",
    2: "Critical Habitat (Polygons)",
}
