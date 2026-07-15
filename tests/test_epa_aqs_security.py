"""
Security tests for the EPA AQS server.

Cover input validation (coordinate/buffer bounds, NaN/inf), that API
credentials are only sourced from environment variables (not hardcoded), and
that validation errors do not leak internal detail. Validation is enforced by
``_validate_geo_inputs`` in ``epa_aqs/server.py`` and the Pydantic ``Field``
bounds on the tool signatures. Credentials come from ``get_aqs_credentials``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_aqs"


def _set_test_credentials() -> None:
    os.environ.setdefault("EPA_AQS_EMAIL", "test@example.com")
    os.environ.setdefault("EPA_AQS_API_KEY", "test-aqs-key")


def _load_server():
    _set_test_credentials()
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_aqs_sec_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_epa_aqs_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_aqs_sec_server"] = module
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


class TestCredentialSourcing:
    def test_credentials_read_from_environment(self, monkeypatch):
        _load_server()  # populates sys.modules["src.apis.aqs_api"]
        api = sys.modules["src.apis.aqs_api"]
        monkeypatch.setenv("EPA_AQS_EMAIL", "env@example.com")
        monkeypatch.setenv("EPA_AQS_API_KEY", "env-key")
        assert api.get_aqs_credentials() == ("env@example.com", "env-key")

    def test_missing_credentials_reported_gracefully(self, monkeypatch):
        module = _load_server()
        monkeypatch.delenv("EPA_AQS_EMAIL", raising=False)
        monkeypatch.delenv("EPA_AQS_API_KEY", raising=False)
        has_creds, msg = module._check_credentials()
        assert has_creds is False
        assert "credentials" in msg.lower()

    def test_no_hardcoded_secret_values_in_source(self):
        for path in [SERVER_DIR / "server.py", SERVER_DIR / "src" / "apis" / "aqs_api.py"]:
            content = path.read_text(encoding="utf-8")
            # Credentials must be pulled from env via os.getenv, never literals.
            assert "test-aqs-key" not in content
            assert 'EPA_AQS_API_KEY"' not in content or "os.getenv" in content

    def test_api_key_only_via_getenv(self):
        content = (SERVER_DIR / "src" / "apis" / "aqs_api.py").read_text(encoding="utf-8")
        assert 'os.getenv("EPA_AQS_API_KEY")' in content
        assert 'os.getenv("EPA_AQS_EMAIL")' in content


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

    def test_credential_error_does_not_leak_key(self, monkeypatch):
        _load_server()  # populates sys.modules["src.apis.aqs_api"]
        api = sys.modules["src.apis.aqs_api"]
        monkeypatch.setenv("EPA_AQS_API_KEY", "super-secret-value")
        monkeypatch.delenv("EPA_AQS_EMAIL", raising=False)
        try:
            api.get_aqs_credentials()
        except ValueError as exc:
            assert "super-secret-value" not in str(exc)
