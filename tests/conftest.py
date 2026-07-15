"""
Shared pytest fixtures for the added per-server test suites.

Several integration tests mock ``ArcGISService`` class methods by direct
assignment (e.g. ``ArcGISService.query_features = staticmethod(...)``). Those
assignments mutate the shared class and, without cleanup, leak across test
files — a later test that relies on the real method (for example, the
tigerweb_counties resilience tests asserting network errors propagate) would
otherwise see a stale mock.

This autouse fixture snapshots the relevant ``ArcGISService`` attributes before
each test and restores them afterward, so tests are order-independent whether
run in isolation or as part of the full suite.
"""

from __future__ import annotations

import pytest

from nepa_mcp_common.arcgis import ArcGISService

_GUARDED_ATTRS = ("query_features", "create_roi_buffer", "simplify_polygon_geometry")


@pytest.fixture(autouse=True)
def _restore_arcgis_service():
    saved = {name: ArcGISService.__dict__.get(name, None) for name in _GUARDED_ATTRS}
    try:
        yield
    finally:
        for name, original in saved.items():
            if original is None:
                # Attribute was inherited / not set directly on the class; drop any override.
                if name in ArcGISService.__dict__:
                    delattr(ArcGISService, name)
            else:
                setattr(ArcGISService, name, original)
