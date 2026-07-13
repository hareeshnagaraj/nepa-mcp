from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def _load_fema_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_test_fema_"):
            sys.modules.pop(module_name, None)

    server_dir = ROOT / "fema_nfhl"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))

    module_path = server_dir / "src" / "apis" / "fema_nfhl_api.py"
    spec = importlib.util.spec_from_file_location("_test_fema_nfhl_api", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_fema_nfhl_api"] = module
    spec.loader.exec_module(module)
    return module


def test_nfhl_paginates_short_pages_when_transfer_limit_exceeded(monkeypatch) -> None:
    fema_api = _load_fema_api()
    calls: list[dict[str, Any]] = []
    pages = [
        {
            "exceededTransferLimit": True,
            "features": [{"attributes": {"OBJECTID": 1}}, {"attributes": {"OBJECTID": 2}}],
        },
        {
            "exceededTransferLimit": False,
            "features": [{"attributes": {"OBJECTID": 3}}],
        },
    ]

    def fake_get(url: str, *, params: dict[str, Any], timeout: int):
        calls.append(params.copy())
        return _FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr(fema_api.requests, "get", fake_get)

    records = fema_api.query_nfhl_layer(28, 29.95, -90.07, radius_miles=10, max_features=5000)

    assert [record["OBJECTID"] for record in records] == [1, 2, 3]
    assert [call["resultOffset"] for call in calls] == [0, 2000]
    assert [call["resultRecordCount"] for call in calls] == [2000, 2000]


def test_nfhl_surfaces_truncation_warning(monkeypatch) -> None:
    fema_api = _load_fema_api()

    def fake_get(url: str, *, params: dict[str, Any], timeout: int):
        return _FakeResponse(
            {
                "exceededTransferLimit": True,
                "features": [{"attributes": {"OBJECTID": 1}}, {"attributes": {"OBJECTID": 2}}],
            }
        )

    monkeypatch.setattr(fema_api.requests, "get", fake_get)

    result = fema_api._query_nfhl_layer_result(28, 29.95, -90.07, radius_miles=10, max_features=2)

    assert result.truncated is True
    assert result.warnings == ["FEMA NFHL layer 28 reached max_features=2; results are partial."]
    assert [record["OBJECTID"] for record in result.records] == [1, 2]
