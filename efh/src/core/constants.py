"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# NOAA ESSENTIAL FISH HABITAT (EFH Mapper)
# =============================================================================

# Public services used by NOAA's EFH Mapper report.
EFH_MAPPER_EFH_SERVICE_URL = "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/EFH/FeatureServer"
EFH_MAPPER_EFH_LAYER_ID = 0
EFH_MAPPER_HAPC_SERVICE_URL = "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/HAPC/FeatureServer"
EFH_MAPPER_HAPC_LAYER_ID = 0
EFH_MAPPER_EFHA_SERVICE_URL = "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/EFHA/FeatureServer"
EFH_MAPPER_EFHA_LAYER_ID = 0
EFH_MAPPER_PACIFIC_SALMON_SERVICE_URL = (
    "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Pacific_salmon_efh/FeatureServer"
)
EFH_MAPPER_PACIFIC_SALMON_LAYER_ID = 0
