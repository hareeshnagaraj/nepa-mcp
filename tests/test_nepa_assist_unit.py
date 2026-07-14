"""
Unit tests for the NEPA Assist API layer (``nepa_assist/src/apis/nepa_assist_api.py``).

These exercise the pure parsing/categorizing/formatting logic with the HTTP
(``requests``) and ArcGIS ROI layers mocked, so no network calls are made. They
follow the same dynamic per-server import pattern used by the USACE test suite.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_nepa_assist_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "nepa_assist"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_nepa_assist_unit_api",
            server_dir / "src" / "apis" / "nepa_assist_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_nepa_assist_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


# ---------------------------------------------------------------------------
# HTML fixture helpers (mimic the EPA NEPAssist "report" table structure)
# ---------------------------------------------------------------------------


def _row(css_class: str, question: str, answer: str) -> str:
    return (
        f'<tr class="{css_class}">'
        f'<td class="questionText"><a href="#">{question}</a></td>'
        f'<td><a href="#">{answer}</a></td>'
        f"</tr>"
    )


def _build_html(rows) -> str:
    body = "".join(rows)
    return f"<html><body><table>{body}</table></body></html>"


# A representative fixture that touches every category.
_MIXED_ROWS = [
    _row("yes0", "Is the site in an ozone non-attainment area?", "Yes"),
    _row("no0", "Is there a lead maintenance area nearby?", "No"),
    _row("yes1", "Is there a stream within the buffer?", "Yes"),
    _row("no1", "Does an NPDES water discharger exist nearby?", "No"),
    _row("yes0", "Is there a superfund site in the area?", "Yes"),
    _row("no0", "Are there any brownfield sites?", "No"),
    _row("yes1", "Is there a school within the buffer?", "Yes"),
    _row("no1", "Is critical habitat present?", "No"),
    _row("yes0", "Is there a historic property nearby?", "Yes"),
    _row("no0", "Is this an unclassified environmental factor?", "No"),
]


class _FakeResponse:
    def __init__(self, text: str, url: str = "https://nepassisttool.epa.gov/nepassist/analysis.aspx?f=report"):
        self.text = text
        self.url = url

    def raise_for_status(self):
        return None


def _patch_http(api, monkeypatch, html: str):
    """Mock the ROI buffer and the requests.get HTTP layer."""
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY))

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(html)

    fake_requests = types.SimpleNamespace(get=fake_get, exceptions=api.requests.exceptions)
    monkeypatch.setattr(api, "requests", fake_requests)


# ---------------------------------------------------------------------------
# Coordinate helper
# ---------------------------------------------------------------------------


class TestCreateRoiPolygonCoords:
    def test_returns_lon_lat_bbox_string(self, monkeypatch):
        api = _load_nepa_assist_api()
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY))
        coords = api.create_roi_polygon_coords(34.5, -106.5, 25.0)
        # 5 lon,lat pairs => 10 comma-separated values (closed bbox).
        parts = coords.split(",")
        assert len(parts) == 10
        # First value should be a longitude (negative here).
        assert float(parts[0]) < 0

    def test_missing_rings_raises(self, monkeypatch):
        api = _load_nepa_assist_api()
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: {"rings": []}))
        import pytest

        with pytest.raises(ValueError):
            api.create_roi_polygon_coords(34.5, -106.5, 25.0)


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------


class TestCategorizeResult:
    def _empty(self, api):
        return {
            "air_quality": {},
            "water_resources": {},
            "contaminated_sites": {},
            "community_features": {},
            "natural_resources": {},
            "cultural_resources": {},
            "summary": {"total_checks": 0, "yes_count": 0, "no_count": 0, "flagged_issues": []},
        }

    def test_air_quality_bucket(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "Ozone non-attainment area?", "yes")
        assert results["air_quality"]["Ozone non-attainment area?"] == "yes"

    def test_water_resources_bucket(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "Is there a wetland present?", "no")
        assert "Is there a wetland present?" in results["water_resources"]

    def test_contaminated_sites_bucket(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "Superfund site nearby?", "yes")
        assert "Superfund site nearby?" in results["contaminated_sites"]

    def test_community_features_bucket(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "School within one mile?", "yes")
        assert "School within one mile?" in results["community_features"]

    def test_natural_resources_bucket(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "Critical habitat present?", "yes")
        assert "Critical habitat present?" in results["natural_resources"]

    def test_cultural_resources_bucket(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "Historic property nearby?", "yes")
        assert "Historic property nearby?" in results["cultural_resources"]

    def test_unmatched_goes_to_other(self):
        api = _load_nepa_assist_api()
        results = self._empty(api)
        api.categorize_result(results, "Some unrelated question?", "no")
        assert results["other"]["Some unrelated question?"] == "no"


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


class TestParseNepaAssistResults:
    def _soup(self, api, html):
        return api.BeautifulSoup(html, "html.parser")

    def test_counts_and_flags_yes_answers(self):
        api = _load_nepa_assist_api()
        soup = self._soup(api, _build_html(_MIXED_ROWS))
        results = api.parse_nepa_assist_results(soup)
        summary = results["summary"]
        assert summary["total_checks"] == 10
        assert summary["yes_count"] == 5
        assert summary["no_count"] == 5
        assert len(summary["flagged_issues"]) == 5

    def test_routes_questions_into_categories(self):
        api = _load_nepa_assist_api()
        soup = self._soup(api, _build_html(_MIXED_ROWS))
        results = api.parse_nepa_assist_results(soup)
        assert results["air_quality"]
        assert results["water_resources"]
        assert results["contaminated_sites"]
        assert results["community_features"]
        assert results["natural_resources"]
        assert results["cultural_resources"]

    def test_empty_table_yields_zero_checks(self):
        api = _load_nepa_assist_api()
        soup = self._soup(api, _build_html([]))
        results = api.parse_nepa_assist_results(soup)
        assert results["summary"]["total_checks"] == 0
        assert results["summary"]["flagged_issues"] == []

    def test_rows_missing_question_link_are_skipped(self):
        api = _load_nepa_assist_api()
        bad_row = '<tr class="yes0"><td class="questionText">No link here</td><td><a href="#">Yes</a></td></tr>'
        soup = self._soup(api, _build_html([bad_row]))
        results = api.parse_nepa_assist_results(soup)
        assert results["summary"]["total_checks"] == 0


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatCategory:
    def test_yes_and_no_symbols(self):
        api = _load_nepa_assist_api()
        out = api.format_category({"Q1": "yes", "Q2": "no"})
        assert "[!] YES - Q1" in out
        assert "[OK] NO - Q2" in out


class TestFormatNepaAssistReport:
    def _query(self, api, html):
        return {
            **api.parse_nepa_assist_results(api.BeautifulSoup(html, "html.parser")),
            "metadata": {
                "latitude": 34.5,
                "longitude": -106.5,
                "buffer_miles": 25.0,
                "project_title": "Test Project",
                "api_url": "https://nepassisttool.epa.gov/nepassist/analysis.aspx",
            },
        }

    def test_report_has_header_and_sections(self):
        api = _load_nepa_assist_api()
        results = self._query(api, _build_html(_MIXED_ROWS))
        report = api.format_nepa_assist_report(results)
        assert "EPA NEPA ASSIST ENVIRONMENTAL SCREENING REPORT" in report
        assert "EXECUTIVE SUMMARY" in report
        assert "AIR QUALITY" in report
        assert "WATER RESOURCES" in report
        assert "CONTAMINATED SITES" in report
        assert "COMMUNITY FEATURES" in report
        assert "NATURAL RESOURCES" in report
        assert "CULTURAL RESOURCES" in report
        assert "NEPA COMPLIANCE GUIDANCE" in report

    def test_report_echoes_location_and_project(self):
        api = _load_nepa_assist_api()
        results = self._query(api, _build_html(_MIXED_ROWS))
        report = api.format_nepa_assist_report(results)
        assert "(34.5, -106.5)" in report
        assert "Test Project" in report
        assert "25.0 miles" in report

    def test_report_lists_flagged_concerns(self):
        api = _load_nepa_assist_api()
        results = self._query(api, _build_html(_MIXED_ROWS))
        report = api.format_nepa_assist_report(results)
        assert "FLAGGED ENVIRONMENTAL CONCERNS" in report

    def test_clean_screening_shows_ok_message(self):
        api = _load_nepa_assist_api()
        clean_rows = [_row("no0", "Is there a stream within the buffer?", "No")]
        results = self._query(api, _build_html(clean_rows))
        report = api.format_nepa_assist_report(results)
        assert "No major environmental concerns flagged" in report

    def test_missing_project_title_shows_na(self):
        api = _load_nepa_assist_api()
        results = self._query(api, _build_html([_row("no0", "Any stream?", "No")]))
        results["metadata"]["project_title"] = ""
        report = api.format_nepa_assist_report(results)
        assert "Project: N/A" in report


# ---------------------------------------------------------------------------
# Compliance guidance
# ---------------------------------------------------------------------------


class TestGenerateComplianceGuidance:
    def _base(self):
        return {
            "air_quality": {},
            "water_resources": {},
            "contaminated_sites": {},
            "natural_resources": {},
            "cultural_resources": {},
        }

    def test_air_quality_guidance_emitted_on_yes(self):
        api = _load_nepa_assist_api()
        results = self._base()
        results["air_quality"] = {"Ozone?": "yes"}
        out = api.generate_compliance_guidance(results)
        assert "AIR QUALITY COMPLIANCE:" in out
        assert "General Conformity" in out

    def test_water_guidance_mentions_section_404(self):
        api = _load_nepa_assist_api()
        results = self._base()
        results["water_resources"] = {"Wetland?": "yes"}
        out = api.generate_compliance_guidance(results)
        assert "WATER RESOURCES COMPLIANCE:" in out
        assert "Section 404" in out

    def test_contaminated_guidance_emitted(self):
        api = _load_nepa_assist_api()
        results = self._base()
        results["contaminated_sites"] = {"Superfund?": "yes"}
        out = api.generate_compliance_guidance(results)
        assert "CONTAMINATED SITES COMPLIANCE:" in out

    def test_natural_resources_guidance_mentions_esa(self):
        api = _load_nepa_assist_api()
        results = self._base()
        results["natural_resources"] = {"Critical habitat?": "yes"}
        out = api.generate_compliance_guidance(results)
        assert "NATURAL RESOURCES COMPLIANCE:" in out
        assert "ESA Section 7" in out

    def test_cultural_guidance_mentions_section_106(self):
        api = _load_nepa_assist_api()
        results = self._base()
        results["cultural_resources"] = {"Historic?": "yes"}
        out = api.generate_compliance_guidance(results)
        assert "CULTURAL RESOURCES COMPLIANCE:" in out
        assert "Section 106" in out

    def test_no_flags_yields_general_guidance(self):
        api = _load_nepa_assist_api()
        out = api.generate_compliance_guidance(self._base())
        assert "GENERAL NEPA COMPLIANCE:" in out


# ---------------------------------------------------------------------------
# query_nepa_assist (HTTP mocked end-to-end within the api layer)
# ---------------------------------------------------------------------------


class TestQueryNepaAssist:
    def test_query_parses_and_adds_metadata(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_http(api, monkeypatch, _build_html(_MIXED_ROWS))
        results = api.query_nepa_assist(34.5, -106.5, 25.0, "My Project")
        assert results["summary"]["total_checks"] == 10
        assert results["summary"]["yes_count"] == 5
        assert results["metadata"]["latitude"] == 34.5
        assert results["metadata"]["longitude"] == -106.5
        assert results["metadata"]["buffer_miles"] == 25.0
        assert results["metadata"]["project_title"] == "My Project"
        assert "api_url" in results["metadata"]
