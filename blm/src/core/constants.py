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


# BLM Land Use Plans (Approved) - for conformance checks per 43 CFR 1610.5
BLM_LAND_USE_PLANS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_Use_Plans_Approved_2022/FeatureServer"
BLM_LAND_USE_PLANS_LAYER_ID = 1

# BLM Wilderness Areas - designated wilderness under the Wilderness Act
BLM_WILDERNESS_AREAS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_Wilderness_Areas_Polygons/FeatureServer"
BLM_WILDERNESS_AREAS_LAYER_ID = 2

# BLM National Monuments and National Conservation Areas
BLM_NATIONAL_MONUMENTS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_National_Monuments_National_Conservation_Areas_Polygons/FeatureServer"
BLM_NATIONAL_MONUMENTS_LAYER_ID = 0
