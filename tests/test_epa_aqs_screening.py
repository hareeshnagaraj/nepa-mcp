from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_aqs_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_test_epa_"):
            sys.modules.pop(module_name, None)

    server_dir = ROOT / "epa_aqs"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    module_path = server_dir / "src" / "apis" / "aqs_api.py"
    spec = importlib.util.spec_from_file_location("_test_epa_aqs_api", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_epa_aqs_api"] = module
    spec.loader.exec_module(module)
    return module


def test_naaqs_screening_classifies_only_annual_standards() -> None:
    aqs_api = _load_aqs_api()

    result = aqs_api.assess_naaqs_compliance(
        [
            {
                "parameter_code": "88101",
                "arithmetic_mean": "10.5",
                "first_max_value": "24.0",
                "primary_exceedance_count": "0",
                "site_number": "001",
            },
            {
                "parameter_code": "44201",
                "arithmetic_mean": "0.030",
                "first_max_value": "0.080",
                "primary_exceedance_count": "0",
                "site_number": "002",
            },
        ]
    )

    assert result["PM2.5"]["comparison_status"] == "above"
    assert result["PM2.5"]["exceeds_standard"] is True
    assert result["Ozone"]["comparison_status"] == "not_evaluated"
    assert result["Ozone"]["exceeds_standard"] is None


def test_air_quality_summary_labels_short_duration_standards_as_context_only() -> None:
    aqs_api = _load_aqs_api()
    compliance = {
        "Ozone": {
            "avg_annual_mean": 0.03,
            "max_value": 0.08,
            "naaqs_standard": 0.07,
            "naaqs_units": "ppm",
            "naaqs_averaging_time": "8-hour",
            "exceeds_standard": None,
            "comparison_status": "not_evaluated",
            "comparison_note": "Selected NAAQS value uses a short-duration form; annual AQS means are shown for context only.",
            "exceedance_percent": None,
            "total_exceedance_days": 0,
            "num_records": 1,
            "num_monitors": 1,
        }
    }

    summary = aqs_api.format_air_quality_summary(
        annual_data=[{"parameter_code": "44201"}],
        compliance=compliance,
        lat=38.9,
        lon=-77.03,
        buffer_miles=8,
        begin_year=2025,
        end_year=2025,
    )

    assert "Short-duration NAAQS values are shown for context only." in summary
    assert "Context only; no annual-mean NAAQS status assigned" in summary
    assert "Pollutants at or below selected annual NAAQS value**: 0" in summary
