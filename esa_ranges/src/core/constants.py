"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# NOAA ESA SPECIES RANGES — WEST COAST REGION
# =============================================================================

# NOAA Fisheries ESA Species Ranges FeatureServer (diced geometry for performance)
ESA_RANGES_SERVICE_URL = "https://maps.fisheries.noaa.gov/server/rest/services/Hosted/Ranges_dice/FeatureServer"
ESA_RANGES_LAYER_ID = 2  # ranges_20250429_merge_wm_dice (CA + southern OR)
ESA_RANGES_FISH_LAYER_ID = 1  # fish_web_dice_vertices1000 (WA/ID/OR + transboundary)
