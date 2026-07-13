"""Shared input validation for geospatial MCP tools."""

from __future__ import annotations

from typing import Any, Tuple

MIN_DISTANCE_MILES = 0.1
MAX_DISTANCE_MILES = 100.0

NOAA_WEST_COAST_EXPECTED_BOUNDS = {
    "min_lat": 24.0,
    "max_lat": 55.5,
    "min_lon": -135.0,
    "max_lon": -100.0,
}

PCSRF_PROJECT_EXPECTED_BOUNDS = {
    "min_lat": 24.0,
    "max_lat": 72.0,
    "min_lon": -180.0,
    "max_lon": -100.0,
}


def validate_coordinates(
    lat: float,
    lon: float,
    buffer_miles: float = 25.0,
    *,
    min_distance_miles: float = MIN_DISTANCE_MILES,
    max_distance_miles: float = MAX_DISTANCE_MILES,
) -> Tuple[float, float, float]:
    """Validate geographic coordinates and buffer distance.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        buffer_miles: Buffer radius in miles.
        min_distance_miles: Smallest accepted buffer distance.
        max_distance_miles: Largest accepted buffer distance.

    Returns:
        Tuple of validated ``(lat, lon, buffer_miles)`` values as floats.

    Raises:
        ValueError: If a coordinate or distance is outside the accepted range.
    """
    lat = float(lat)
    lon = float(lon)
    buffer_miles = float(buffer_miles)

    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude must be between -90 and 90, got {lat}")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude must be between -180 and 180, got {lon}")
    if not min_distance_miles <= buffer_miles <= max_distance_miles:
        raise ValueError(
            f"Buffer miles must be between {min_distance_miles} and {max_distance_miles}, got {buffer_miles}"
        )

    return lat, lon, buffer_miles


def add_empty_result_coverage_warning(
    result: dict[str, Any],
    query_geometry: dict[str, Any],
    *,
    bounds: dict[str, float],
    dataset_name: str,
) -> dict[str, Any]:
    """Annotate an empty result when the queried buffer misses expected coverage.

    The upstream query must already have run. This helper never suppresses a
    request, and it checks the full point-buffer envelope rather than only its
    center so buffers that overlap the expected service geography are not
    mislabeled.
    """
    if result.get("total") != 0 or _geometry_intersects_bounds(query_geometry, bounds):
        return result

    result["outside_expected_coverage"] = True
    result["coverage_warning"] = (
        f"The queried area is outside the expected geographic coverage of {dataset_name}. "
        "An empty response should not be interpreted as confirmation that the resource is absent."
    )
    return result


def _geometry_intersects_bounds(
    geometry: dict[str, Any],
    bounds: dict[str, float],
) -> bool:
    rings = geometry.get("rings")
    if not isinstance(rings, list) or not rings:
        return True

    coordinates = [coordinate for ring in rings if isinstance(ring, list) for coordinate in ring]
    valid_coordinates = [
        coordinate for coordinate in coordinates if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2
    ]
    if not valid_coordinates:
        return True

    min_lon = min(float(coordinate[0]) for coordinate in valid_coordinates)
    max_lon = max(float(coordinate[0]) for coordinate in valid_coordinates)
    min_lat = min(float(coordinate[1]) for coordinate in valid_coordinates)
    max_lat = max(float(coordinate[1]) for coordinate in valid_coordinates)

    return not (
        max_lon < bounds["min_lon"]
        or min_lon > bounds["max_lon"]
        or max_lat < bounds["min_lat"]
        or min_lat > bounds["max_lat"]
    )
