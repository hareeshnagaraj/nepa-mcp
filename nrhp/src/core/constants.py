"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# NATIONAL REGISTER OF HISTORIC PLACES (NRHP) - NPS
# =============================================================================

# NPS ArcGIS MapServer hosting NRHP point and polygon layers
NRHP_SERVICE_URL = "https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer"

# Layer IDs within the NRHP MapServer
NRHP_LAYERS = {
    0: "Historic Places (Points)",
    1: "Historic Places (Polygons)",
}
