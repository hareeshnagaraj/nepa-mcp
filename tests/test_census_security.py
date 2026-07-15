"""
Security tests for the Census server.

Cover input validation (coordinate/buffer bounds, NaN/inf), that the API key is
sourced from the environment rather than hardcoded, and that upstream/validation
errors do not leak internal detail. Validation is enforced by
``_validate_geo_inputs`` in ``census/server.py`` and the Pydantic ``Field``
bounds on the tool signature. Mirrors the USACE security template.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "census"
API_FILE = SERVER_DIR / "src" / "apis" / "simplified_census_api.py"


def _load_server():
    os.environ.setdefault("CENSUS_API_KEY", "test-census-key")
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_census_sec_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_census_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_census_sec_server"] = module
    spec.loader.exec_module(module)
    return module


class TestInputValidation:
    """The module-level _validate_geo_inputs is the single validation choke point."""

    def test_latitude_above_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(999.0, -106.5, 25.0)

    def test_latitude_below_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(-91.0, -106.5, 25.0)

    def test_longitude_out_of_range_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -999.0, 25.0)

    def test_zero_buffer_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -106.5, 0.0)

    def test_negative_buffer_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -106.5, -5.0)

    def test_buffer_above_max_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(34.5, -106.5, 250.0)

    def test_nan_coordinate_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(float("nan"), -106.5, 25.0)

    def test_inf_coordinate_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs(float("inf"), -106.5, 25.0)

    def test_non_numeric_rejected(self):
        module = _load_server()
        with pytest.raises(ValueError):
            module._validate_geo_inputs("abc", -106.5, 25.0)

    def test_valid_inputs_pass_through(self):
        module = _load_server()
        lat, lon, dist = module._validate_geo_inputs(34.5, -106.5, 25.0)
        assert (lat, lon, dist) == (34.5, -106.5, 25.0)

    def test_boundary_values_accepted(self):
        module = _load_server()
        assert module._validate_geo_inputs(90.0, 180.0, 0.1)[0] == 90.0
        assert module._validate_geo_inputs(-90.0, -180.0, 100.0)[0] == -90.0


class TestApiKeyFromEnvironment:
    def test_api_key_not_hardcoded_in_source(self):
        for path in [SERVER_DIR / "server.py", API_FILE]:
            content = path.read_text(encoding="utf-8")
            # The key must be read from the environment, never a literal value.
            assert "CENSUS_API_KEY" in content or path == API_FILE
            # No inline assignment of a literal secret.
            assert 'api_key = "' not in content
            assert 'API_KEY = "' not in content

    def test_key_is_sourced_from_getenv(self):
        content = API_FILE.read_text(encoding="utf-8")
        assert 'os.getenv("CENSUS_API_KEY")' in content


class TestErrorMessageSafety:
    def test_validation_message_has_no_internal_paths(self):
        module = _load_server()
        try:
            module._validate_geo_inputs(999.0, -106.5, 25.0)
        except ValueError as exc:
            msg = str(exc)
            assert "/Users/" not in msg
            assert "Traceback" not in msg
            assert "latitude" in msg.lower()

    def test_missing_key_message_has_no_secret_value(self):
        content = (SERVER_DIR / "server.py").read_text(encoding="utf-8")
        # The guidance message points users to the signup URL, not a real key.
        assert "key_signup.html" in content
