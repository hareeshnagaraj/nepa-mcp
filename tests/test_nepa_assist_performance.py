"""
Performance / scaling tests for the NEPA Assist API layer.

These are hermetic (HTTP and ArcGIS mocked) and assert algorithmic behavior at
larger synthetic result counts: HTML parsing of many question rows stays bounded
in time, categorization scales, and summary tallies stay correct. They do not
hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path

import requests as req_mod

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
            "_nepa_assist_perf_api", server_dir / "src" / "apis" / "nepa_assist_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_nepa_assist_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY))


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.url = "https://nepassisttool.epa.gov/nepassist/analysis.aspx"

    def raise_for_status(self):
        return None


def _install_html(api, monkeypatch, html: str):
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: _FakeResponse(html), exceptions=req_mod.exceptions)
    monkeypatch.setattr(api, "requests", fake_requests)


def _row(css_class: str, question: str, answer: str) -> str:
    return (
        f'<tr class="{css_class}">'
        f'<td class="questionText"><a href="#">{question}</a></td>'
        f'<td><a href="#">{answer}</a></td>'
        f"</tr>"
    )


def _build_html(rows) -> str:
    return f"<html><body><table>{''.join(rows)}</table></body></html>"


class TestParsingThroughput:
    def test_large_result_set_parses_quickly(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        # 2000 alternating yes/no stream questions.
        rows = [
            _row(f"{'yes' if i % 2 == 0 else 'no'}0", f"Is there a stream #{i}?", "Yes" if i % 2 == 0 else "No")
            for i in range(2000)
        ]
        _install_html(api, monkeypatch, _build_html(rows))
        start = time.perf_counter()
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        elapsed = time.perf_counter() - start
        assert results["summary"]["total_checks"] == 2000
        assert results["summary"]["yes_count"] == 1000
        assert results["summary"]["no_count"] == 1000
        # HTML parse + categorization of 2k rows should be comfortably under a few seconds.
        assert elapsed < 5.0


class TestFormattingThroughput:
    def test_report_formatting_bounded(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        rows = [_row("yes0", f"Is there a wetland #{i}?", "Yes") for i in range(1000)]
        _install_html(api, monkeypatch, _build_html(rows))
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        start = time.perf_counter()
        report = api.format_nepa_assist_report(results)
        elapsed = time.perf_counter() - start
        assert "EPA NEPA ASSIST ENVIRONMENTAL SCREENING REPORT" in report
        assert "WATER RESOURCES COMPLIANCE:" in report
        assert elapsed < 2.0


class TestCategorizationScaling:
    def test_all_flagged_issues_recorded(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        rows = [_row("yes0", f"Superfund site #{i}?", "Yes") for i in range(500)]
        _install_html(api, monkeypatch, _build_html(rows))
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        assert len(results["summary"]["flagged_issues"]) == 500
        assert len(results["contaminated_sites"]) == 500
