"""
Constants for the CFR MCP server and API wrapper.

Keep this module limited to shared configuration used by the live CFR tools.
Static title/section quick-reference data belongs in docs, not runtime code.
"""

import os

# =============================================================================
# API Configuration
# =============================================================================

# eCFR API (current regulations and version tracking)
ECFR_BASE_URL = "https://www.ecfr.gov/api/versioner/v1"
ECFR_RENDERER_URL = "https://www.ecfr.gov/api/renderer/v1"
ECFR_ENDPOINTS = {
    "titles": f"{ECFR_BASE_URL}/titles.json",
    "structure": f"{ECFR_BASE_URL}/structure",
    "content": f"{ECFR_RENDERER_URL}/content/enhanced",
    "versions": f"{ECFR_BASE_URL}/versions",
    "ancestry": f"{ECFR_BASE_URL}/ancestry",
}

# Federal Register API (authoritative rulemaking documents)
FEDERAL_REGISTER_BASE_URL = "https://www.federalregister.gov/api/v1"
FEDERAL_REGISTER_ENDPOINTS = {
    "documents": f"{FEDERAL_REGISTER_BASE_URL}/documents.json",
    "document": f"{FEDERAL_REGISTER_BASE_URL}/documents",
}

# =============================================================================
# Runtime Settings
# =============================================================================

REQUEST_TIMEOUT_SECONDS = 30
# Retry/backoff for eCFR + Federal Register HTTP calls. Both APIs rate-limit
# bursts (returning 429s or empty 200 bodies); without retries a throttled
# response silently breaks the FR citation bisection.
HTTP_MAX_RETRIES = 4
HTTP_BACKOFF_BASE_SECONDS = 0.6
# Cache location. Defaults to a writable temp dir so the server works on
# read-only deployment runtimes. Override with CFR_CACHE_DIR for a persistent
# local cache.
DEFAULT_CACHE_DIR = os.environ.get("CFR_CACHE_DIR", "/tmp/cfr")

CACHE_TTL = {
    "titles": 4 * 60 * 60,
    "structure": 24 * 60 * 60,
    "versions": 1 * 60 * 60,
    "current_content": 24 * 60 * 60,
    "historical_content": 30 * 24 * 60 * 60,
}

# =============================================================================
# URL Helpers
# =============================================================================


def get_ecfr_versions_url(title: int) -> str:
    """Get the eCFR Versions API URL for a title."""
    return f"{ECFR_ENDPOINTS['versions']}/title-{title}.json"


def get_ecfr_ancestry_url(title: int, date: str = None) -> str:
    """Get the eCFR Ancestry API URL for a title/date."""
    if date is None:
        date = "current"
    return f"{ECFR_ENDPOINTS['ancestry']}/{date}/title-{title}.json"
