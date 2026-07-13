"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# NOAA PCSRF (Pacific Coastal Salmon Recovery Fund) SERVICES
# =============================================================================

# Base URL for NOAA Fisheries ArcGIS services
_NOAA_ARCGIS_BASE = "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services"

# Species ranges (polygons) — ESA-listed species geographic ranges
PCSRF_SPECIES_RANGES_URL = f"{_NOAA_ARCGIS_BASE}/All_Species_Ranges/FeatureServer"
PCSRF_SPECIES_RANGES_LAYER_ID = 0

# Critical habitat polygons — designated critical habitat areas
PCSRF_CRITICAL_HABITAT_POLY_URL = f"{_NOAA_ARCGIS_BASE}/All_critical_habitat_poly_20210904__generalized/FeatureServer"
PCSRF_CRITICAL_HABITAT_POLY_LAYER_ID = 220

# Critical habitat lines — designated critical habitat (rivers/streams)
PCSRF_CRITICAL_HABITAT_LINE_URL = f"{_NOAA_ARCGIS_BASE}/All_critical_habitat_line_20210904_generalize_v3/FeatureServer"
PCSRF_CRITICAL_HABITAT_LINE_LAYER_ID = 123

# EFH (Essential Fish Habitat) — Atlantic salmon EFH/HAPC buffers
PCSRF_EFH_URL = f"{_NOAA_ARCGIS_BASE}/Atlantic_salmon_EFH_HAPC_Buffer/FeatureServer"
PCSRF_EFH_LAYER_ID = 0

# PCSRF projects (points) — salmon recovery project locations and funding
PCSRF_PROJECTS_URL = f"{_NOAA_ARCGIS_BASE}/PCSRF_Projects_Display/FeatureServer"
PCSRF_PROJECTS_LAYER_ID = 0
