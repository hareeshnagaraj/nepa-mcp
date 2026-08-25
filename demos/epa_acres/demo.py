#!/usr/bin/env python3
"""Demo client for the NEPA-MCP `epa_acres` server.

Launches the server the same way a real MCP client configuration does —
``nepa-mcp server epa_acres`` over stdio — then discovers the MCP contract,
runs live screening scenarios against the EPA Envirofacts Brownfields layer,
verifies each scenario against lightweight expectations, and writes
``report.html`` with the full tool output, demo-issued MCP operations, and the
actual upstream HTTP requests (also persisted as ``audit.jsonl``).

Run from the repository root with its environment:

    uv run python demos/epa_acres/demo.py

Set ``NEPA_MCP_REPO`` only if running against a different checkout.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp import Client
from fastmcp.exceptions import ToolError

DEMO_DIR = Path(__file__).resolve().parent
REPO_DIR = Path(os.environ.get("NEPA_MCP_REPO", DEMO_DIR.parents[1])).resolve()
REPORT_PATH = DEMO_DIR / "report.html"
AUDIT_PATH = DEMO_DIR / "audit.jsonl"
TOOL_NAME = "get_epa_acres_properties_in_roi"

TRACE_HOOK_SOURCE = r"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_trace_path = os.environ.get("NEPA_ACRES_HTTP_TRACE")
if _trace_path:
    _original_request = requests.sessions.Session.request

    def _jsonable(value):
        return json.loads(json.dumps(value, default=str))

    def _write(event):
        with Path(_trace_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _traced_request(self, method, url, **kwargs):
        started = time.perf_counter()
        event = {
            "event": "upstream_http",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method.upper(),
            "url": url,
            "request": {
                key: _jsonable(kwargs[key])
                for key in ("params", "data", "json", "timeout")
                if key in kwargs
            },
        }
        try:
            response = _original_request(self, method, url, **kwargs)
        except Exception as exc:
            event.update(
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            _write(event)
            raise
        event.update(
            status="ok",
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        _write(event)
        return response

    requests.sessions.Session.request = _traced_request
"""

# Each scenario: (title, why it matters, tool arguments, checks on the output).
SCENARIOS = [
    (
        "Urban core — Pittsburgh, PA (5 mi)",
        "Dense Brownfields geography; exercises the 100-record listing cap with a complete returned total.",
        {"latitude": 40.44, "longitude": -79.99, "buffer_miles": 5},
        [
            ("returns ACRES properties", lambda text: "**Total ACRES Properties:** 0" not in text),
            ("records carry FRS registry IDs", lambda text: "FRS Registry ID" in text),
            ("records carry ACRES IDs", lambda text: "ACRES ID" in text),
            ("records link EPA property pages", lambda text: "[EPA property record](https://" in text),
            ("listing cap is disclosed", lambda text: "Listing the first 100 of" in text),
        ],
    ),
    (
        "Neighborhood scale — Pittsburgh, PA (1 mi)",
        "Small ROI; complete listing without the cap.",
        {"latitude": 40.44, "longitude": -79.99, "buffer_miles": 1},
        [
            ("returns ACRES properties", lambda text: "**Total ACRES Properties:** 0" not in text),
            ("no cap note on a small result", lambda text: "Listing the first" not in text),
            ("names the data source", lambda text: "EPA Envirofacts Brownfields ArcGIS layer" in text),
        ],
    ),
    (
        "Rural — central Wyoming (5 mi)",
        "An empty result must keep the ACRES coverage caveats attached.",
        {"latitude": 43.0, "longitude": -107.5, "buffer_miles": 5},
        [
            ("reports zero properties", lambda text: "**Total ACRES Properties:** 0" in text),
            ("empty-result screening note", lambda text: "not evidence that the area" in text),
            ("not-a-complete-inventory disclaimer", lambda text: "not a complete inventory" in text),
        ],
    ),
]

INVALID_SCENARIO = (
    "Validation — latitude 999",
    "Out-of-range input must be rejected before any upstream call.",
    {"latitude": 999, "longitude": -79.99, "buffer_miles": 5},
    [("rejected with a latitude message", lambda text: "latitude" in text.lower())],
)


def server_config(trace_dir: Path, trace_path: Path) -> tuple[dict, str]:
    """Build the same stdio launch a shipped client config uses."""
    launcher = REPO_DIR / ".venv" / "bin" / "nepa-mcp"
    if launcher.exists():
        command, args = str(launcher), ["server", "epa_acres"]
        display_command = "nepa-mcp server epa_acres"
    else:
        command, args = sys.executable, ["-m", "nepa_mcp", "server", "epa_acres"]
        display_command = "python -m nepa_mcp server epa_acres"
    python_path = str(trace_dir)
    if os.environ.get("PYTHONPATH"):
        python_path += os.pathsep + os.environ["PYTHONPATH"]
    config = {
        "mcpServers": {
            "epa_acres": {
                "command": command,
                "args": args,
                "env": {
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONPATH": python_path,
                    "NEPA_ACRES_HTTP_TRACE": str(trace_path),
                },
            }
        }
    }
    return config, display_command


def result_text(result) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "text", None))


def run_checks(checks, text):
    return [(label, bool(check(text))) for label, check in checks]


# --- audit trail -----------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def audit_event(audit: list, method: str, **fields) -> dict:
    entry = {"seq": len(audit) + 1, "timestamp": _now_iso(), "method": method, **fields}
    audit.append(entry)
    return entry


def response_excerpt(text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("**Total"):
            return line.replace("**", "")
    return next((line for line in text.split("\n") if line.strip()), "")[:120]


def read_http_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def identify_service(url: str) -> tuple[str, str]:
    if "/GeometryServer/buffer" in url:
        return "Esri GeometryServer", "Build geodesic ROI"
    if "/MapServer/5/query" in url:
        return "EPA Brownfields layer 5", "Query ACRES properties"
    return "Other upstream", "Supporting request"


async def audited_call_tool(audit: list, client, scenario: str, args: dict, trace_path: Path):
    """Call the MCP tool and correlate every resulting upstream HTTP request."""
    before = len(read_http_trace(trace_path))
    entry = audit_event(audit, "tools/call", tool=TOOL_NAME, scenario=scenario, arguments=args)
    started = time.perf_counter()
    try:
        result = await client.call_tool(TOOL_NAME, args)
    except ToolError as exc:
        elapsed = time.perf_counter() - started
        new_http = read_http_trace(trace_path)[before:]
        entry.update(
            completed_at=_now_iso(),
            duration_ms=round(elapsed * 1000),
            status="error",
            error=str(exc)[:300],
            upstream_http_calls=len(new_http),
        )
        return None, elapsed, exc, new_http
    elapsed = time.perf_counter() - started
    text = result_text(result)
    new_http = read_http_trace(trace_path)[before:]
    entry.update(
        completed_at=_now_iso(),
        duration_ms=round(elapsed * 1000),
        status="ok",
        content_blocks=len(result.content),
        response_chars=len(text),
        response_excerpt=response_excerpt(text),
        upstream_http_calls=len(new_http),
    )
    return text, elapsed, None, new_http


async def run_demo():
    audit: list[dict] = []
    http_events: list[dict] = []
    sections = []
    with tempfile.TemporaryDirectory(prefix="epa-acres-demo-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        trace_path = temp_dir / "upstream-http.jsonl"
        (temp_dir / "sitecustomize.py").write_text(TRACE_HOOK_SOURCE, encoding="utf-8")
        config, display_command = server_config(temp_dir, trace_path)
        print(f"Launching over stdio: {display_command}")
        audit_event(
            audit,
            "demo/start",
            transport="stdio",
            command=display_command,
        )

        async with Client(config) as client:
            # 1. Contract discovery — what any MCP client sees at tools/list.
            entry = audit_event(audit, "tools/list")
            started = time.perf_counter()
            before = len(read_http_trace(trace_path))
            tools = await client.list_tools()
            list_http_count = len(read_http_trace(trace_path)) - before
            entry.update(
                completed_at=_now_iso(),
                duration_ms=round((time.perf_counter() - started) * 1000),
                status="ok",
                tools=[tool.name for tool in tools],
                upstream_http_calls=list_http_count,
            )

            tool = next(t for t in tools if t.name == TOOL_NAME)
            params = tool.inputSchema["properties"]
            contract_lines = [f"Tool: {tool.name}", "", tool.description or "", "", "Arguments:"]
            for name, schema in params.items():
                bounds = f" [{schema.get('minimum')} to {schema.get('maximum')}]"
                default = f" (default {schema['default']})" if "default" in schema else ""
                contract_lines.append(f"- `{name}`{bounds}{default} — {schema.get('description', '')}")
            annotations = tool.annotations
            contract_lines.append(
                f"- annotations: readOnly={annotations.readOnlyHint}, destructive={annotations.destructiveHint}, "
                f"idempotent={annotations.idempotentHint}, openWorld={annotations.openWorldHint}"
            )
            contract_checks = [
                ("single tool advertised", len(tools) == 1),
                ("contract discovery makes no upstream HTTP request", list_http_count == 0),
            ]
            sections.append(
                (
                    "MCP contract (tools/list)",
                    "Discovered over stdio, exactly as an agent sees it.",
                    None,
                    "\n".join(contract_lines),
                    contract_checks,
                    0.0,
                )
            )
            print(f"Contract: {len(tools)} tool discovered — {tool.name}")

            # 2. Live screening scenarios.
            for title, why, args, checks in SCENARIOS:
                text, elapsed, _error, new_http = await audited_call_tool(audit, client, title, args, trace_path)
                for event in new_http:
                    event["scenario"] = title
                    event["service"], event["purpose"] = identify_service(event["url"])
                http_events.extend(new_http)
                outcomes = run_checks(checks, text or "")
                outcomes.append(("captures GeometryServer and EPA layer calls", len(new_http) >= 2))
                sections.append((title, why, args, text or "", outcomes, elapsed))
                passed = sum(1 for _, ok in outcomes if ok)
                print(f"{title}: {passed}/{len(outcomes)} checks passed ({elapsed:.1f}s)")

            # 3. Validation rejection — the error an agent would see.
            title, why, args, checks = INVALID_SCENARIO
            text, elapsed, error, new_http = await audited_call_tool(audit, client, title, args, trace_path)
            for event in new_http:
                event["scenario"] = title
                event["service"], event["purpose"] = identify_service(event["url"])
            http_events.extend(new_http)
            if error is not None:
                text = f"ToolError (as expected):\n\n{error}"
            elif text is None:
                text = "UNEXPECTED: the call succeeded"
            outcomes = run_checks(checks, text)
            outcomes.append(("rejected before upstream HTTP", not new_http))
            sections.append((title, why, args, text, outcomes, elapsed))
            passed = sum(1 for _, ok in outcomes if ok)
            print(f"{title}: {passed}/{len(outcomes)} checks passed ({elapsed:.1f}s)")

    mcp_count = sum(entry["method"].startswith("tools/") for entry in audit)
    audit_event(audit, "demo/end", mcp_operations=mcp_count, upstream_http_calls=len(http_events))
    combined = [{"stream": "mcp" if entry["method"].startswith("tools/") else "demo", **entry} for entry in audit]
    combined.extend({"stream": "upstream_http", **entry} for entry in http_events)
    combined.sort(key=lambda entry: entry["timestamp"])
    for index, entry in enumerate(combined, 1):
        entry["audit_seq"] = index
    AUDIT_PATH.write_text("".join(json.dumps(entry) + "\n" for entry in combined), encoding="utf-8")
    print(f"Audit trail: {mcp_count} MCP operations + {len(http_events)} upstream calls")
    return sections, audit, http_events


# --- minimal markdown-to-HTML rendering for the report (no dependencies) ---


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)


def markdown_to_html(markdown: str) -> str:
    parts, in_list = [], False

    def close_list():
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for line in markdown.split("\n"):
        if line.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_inline(line[2:])}</li>")
            continue
        close_list()
        if line.startswith("### "):
            parts.append(f"<h4>{_inline(line[4:])}</h4>")
        elif line.startswith("## "):
            parts.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.startswith("> "):
            parts.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        elif line.strip() == "---":
            parts.append("<hr>")
        elif line.strip():
            parts.append(f"<p>{_inline(line)}</p>")
    close_list()
    return "\n".join(parts)


def audit_table_html(audit: list) -> str:
    rows = []
    for entry in audit:
        args = entry.get("arguments")
        detail = ""
        if entry["method"] == "demo/start":
            detail = entry["command"]
            args = None
        elif entry["method"] == "tools/list":
            detail = ", ".join(entry.get("tools", []))
        elif entry["method"] == "tools/call":
            if entry.get("status") == "ok":
                detail = (
                    f"{entry.get('response_chars', 0):,} chars; "
                    f"{entry.get('upstream_http_calls', 0)} upstream — "
                    f"{entry.get('response_excerpt', '')}"
                )
            else:
                detail = f"{entry.get('upstream_http_calls', 0)} upstream — {entry.get('error', '')[:160]}"
        elif entry["method"] == "demo/end":
            detail = (
                f"{entry.get('mcp_operations', 0)} MCP operations; {entry.get('upstream_http_calls', 0)} upstream calls"
            )
        status = entry.get("status", "—")
        status_class = {"ok": "ok", "error": "err"}.get(status, "")
        rows.append(
            "<tr>"
            f"<td>{entry['seq']}</td>"
            f"<td>{html.escape(entry['timestamp'].split('T')[1].split('+')[0])}</td>"
            f"<td>{html.escape(entry['method'])}</td>"
            f"<td>{html.escape(json.dumps(args) if args else '')}</td>"
            f"<td class='num'>{entry.get('duration_ms', '')}</td>"
            f"<td class='{status_class}'>{html.escape(str(status))}</td>"
            f"<td>{html.escape(detail)}</td>"
            "</tr>"
        )
    return (
        '<div class="tablewrap"><table><thead><tr>'
        "<th>#</th><th>Time (UTC)</th><th>Method</th><th>Arguments</th>"
        "<th>ms</th><th>Status</th><th>Detail</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _display_request(event: dict) -> str:
    request = event.get("request", {})
    payload = request.get("params") or request.get("data") or request.get("json") or {}
    display = dict(payload) if isinstance(payload, dict) else {"payload": payload}
    for key in ("geometry", "geometries"):
        if key in display:
            value = str(display[key])
            display[key] = f"<{len(value):,} chars; full value in audit.jsonl>"
    if "timeout" in request:
        display["timeout"] = request["timeout"]
    return json.dumps(display, sort_keys=True)


def http_table_html(events: list[dict]) -> str:
    rows = []
    for index, event in enumerate(events, 1):
        endpoint = urlsplit(event["url"]).path
        status = event.get("status", "—")
        status_class = {"ok": "ok", "error": "err"}.get(status, "")
        response = event.get("status_code", event.get("error", ""))
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(event.get('scenario', ''))}</td>"
            f"<td>{html.escape(event.get('service', ''))}</td>"
            f"<td>{html.escape(event.get('purpose', ''))}</td>"
            f"<td>{html.escape(event['method'])}</td>"
            f"<td>{html.escape(endpoint)}</td>"
            f"<td><code>{html.escape(_display_request(event))}</code></td>"
            f"<td class='num'>{event.get('duration_ms', '')}</td>"
            f"<td class='{status_class}'>{html.escape(str(response))}</td>"
            "</tr>"
        )
    return (
        '<div class="tablewrap"><table><thead><tr>'
        "<th>#</th><th>Scenario</th><th>Service</th><th>Purpose</th><th>Verb</th>"
        "<th>Endpoint</th><th>Exact request fields</th><th>ms</th><th>HTTP</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def write_report(sections, audit, http_events) -> None:
    total_checks = sum(len(outcomes) for *_rest, outcomes, _e in sections)
    total_passed = sum(1 for *_rest, outcomes, _e in sections for _, ok in outcomes if ok)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = []
    for title, why, args, text, outcomes, elapsed in sections:
        checks_html = "".join(
            f'<li class="{"ok" if ok else "fail"}">{"✔" if ok else "✘"} {html.escape(label)}</li>'
            for label, ok in outcomes
        )
        args_html = (
            f"<code>{html.escape(', '.join(f'{k}={v}' for k, v in args.items()))}</code>"
            if args
            else "<code>tools/list</code>"
        )
        timing = f" · {elapsed:.1f}s" if elapsed else ""
        open_attribute = " open" if title.startswith("MCP contract") else ""
        blocks.append(
            f"""
      <section>
        <h2>{html.escape(title)}</h2>
        <p class="why">{html.escape(why)}</p>
        <p class="meta">{args_html}{timing}</p>
        <ul class="checks">{checks_html}</ul>
        <details{open_attribute}><summary>MCP result returned to the demo client</summary>
          <div class="output">{markdown_to_html(text)}</div>
        </details>
      </section>"""
        )

    REPORT_PATH.write_text(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>epa_acres demo report</title>
<style>
  body {{ font: 15px/1.55 -apple-system, "Segoe UI", sans-serif; margin: 0 auto; max-width: 60rem;
         padding: 2rem 1.25rem 4rem; color: #1d2733; background: #f7f8fa; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .25rem; }}
  .subtitle {{ color: #57606c; margin-top: 0; }}
  .scorecard {{ display: inline-block; padding: .35rem .8rem; border-radius: .5rem; font-weight: 600;
               background: {"#e5f4e8; color: #1d6f34" if total_passed == total_checks else "#fdecea; color: #9f2318"}; }}
  section {{ background: #fff; border: 1px solid #e3e7ec; border-radius: .6rem; padding: 1.1rem 1.4rem;
            margin: 1.25rem 0; }}
  section h2 {{ font-size: 1.15rem; margin: 0 0 .2rem; }}
  .why {{ color: #57606c; margin: .1rem 0 .4rem; }}
  .meta code {{ background: #eef1f5; padding: .15rem .45rem; border-radius: .3rem; }}
  ul.checks {{ list-style: none; padding: 0; margin: .5rem 0; }}
  ul.checks li {{ padding: .1rem 0; }}
  ul.checks li.ok {{ color: #1d6f34; }}
  ul.checks li.fail {{ color: #9f2318; font-weight: 600; }}
  details {{ margin-top: .5rem; }}
  summary {{ cursor: pointer; color: #375a86; }}
  .output {{ border-left: 3px solid #dfe4ea; margin-top: .6rem; padding: .1rem 1rem; overflow-x: auto; }}
  .output blockquote {{ margin: .4rem 0; padding: .3rem .8rem; background: #f4f6e8; border-left: 3px solid #b8b96a;
                       color: #4e522c; }}
  .output ul {{ padding-left: 1.2rem; }}
  .output li {{ margin: .25rem 0; }}
  .output a {{ color: #375a86; }}
  .flow {{ display: grid; gap: .45rem; padding-left: 1.4rem; }}
  .flow li {{ padding: .3rem .5rem; background: #f7f8fa; border-left: 3px solid #8da6c4; }}
  .boundary {{ padding: .6rem .8rem; background: #fff8df; border-left: 3px solid #d8b84b; }}
  hr {{ border: 0; border-top: 1px solid #e3e7ec; }}
  .tablewrap {{ overflow-x: auto; margin-top: .6rem; }}
  table {{ border-collapse: collapse; font: 12.5px/1.45 ui-monospace, "SF Mono", Menlo, monospace;
          white-space: nowrap; }}
  th, td {{ border: 1px solid #e3e7ec; padding: .3rem .55rem; text-align: left; vertical-align: top; }}
  th {{ background: #eef1f5; font-weight: 600; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.ok {{ color: #1d6f34; }}
  td.err {{ color: #9f2318; }}
  footer {{ color: #7a838d; font-size: .85rem; margin-top: 2rem; }}
</style></head>
<body>
  <h1>EPA ACRES Brownfields MCP server — live demo report</h1>
  <p class="subtitle">nepa-mcp <code>epa_acres</code> · tool <code>{TOOL_NAME}</code> · generated {generated}</p>
  <p><span class="scorecard">{total_passed}/{total_checks} checks passed</span></p>
  <section>
    <h2>What called what</h2>
    <ol class="flow">
      <li><b>Demo client:</b> discovers the contract with <code>tools/list</code>, then invokes
      <code>{TOOL_NAME}</code> with latitude, longitude, and buffer miles.</li>
      <li><b>MCP transport:</b> FastMCP carries <code>tools/call</code> over local stdio to
      <code>nepa-mcp server epa_acres</code>. This is the MCP layer.</li>
      <li><b>Server validation:</b> Pydantic rejects invalid coordinates before network I/O.</li>
      <li><b>Esri request:</b> shared <code>ArcGISService</code> sends <code>GET /GeometryServer/buffer</code>
      to create a geodesic WGS84 polygon.</li>
      <li><b>EPA request:</b> shared <code>ArcGISService</code> sends
      <code>POST /EMEF/efpoints/MapServer/5/query</code> to the EPA Brownfields layer, paging with
      <code>resultOffset</code> and <code>resultRecordCount</code>.</li>
      <li><b>MCP result:</b> the server normalizes ACRES fields and returns caveated Markdown to the client.</li>
    </ol>
    <p class="boundary"><b>API boundary:</b> there is no separate call to the ACRES grant-reporting
    application. ACRES is the property data exposed by EPA Brownfields ArcGIS layer 5. The buffer call is
    an Esri geometry utility; the layer query is the EPA data call; <code>tools/call</code> is MCP.</p>
  </section>
  <section>
    <h2>Result-state semantics</h2>
    <div class="tablewrap"><table><thead><tr><th>State</th><th>Meaning</th></tr></thead><tbody>
      <tr><td>Complete</td><td><code>truncated=false</code>; returned total is exact for this query.</td></tr>
      <tr><td>Empty</td><td>Complete query with zero matches; the coverage caveats in the tool output still apply.</td></tr>
      <tr><td>Partial</td><td>Shared 10,000-record safety cap reached; a warning marks the results as partial.</td></tr>
      <tr><td>Display capped</td><td>All rows were counted, but Markdown lists only the first 100.</td></tr>
      <tr><td>Unavailable</td><td>Buffer or EPA query failed; distinct from zero matches.</td></tr>
      <tr><td>Invalid</td><td>Input rejected before any upstream HTTP request.</td></tr>
    </tbody></table></div>
  </section>
  {"".join(blocks)}
  <section>
    <h2>Upstream HTTP audit</h2>
    <p class="why">Actual requests emitted inside the server. Geometry payloads are summarized here;
    <code>audit.jsonl</code> preserves their full values and all paging fields.</p>
    {http_table_html(http_events)}
  </section>
  <section>
    <h2>Demo and MCP operation log</h2>
    <p class="why">Synthetic demo start/end markers plus MCP operations explicitly issued after the client's
    implicit session setup. This is not a raw wire capture. Correlated upstream counts prove which calls
    reached the network.</p>
    {audit_table_html(audit)}
  </section>
  <footer>Server launched over MCP stdio (<code>nepa-mcp server epa_acres</code>) against the live EPA
  Envirofacts Brownfields ArcGIS layer. Screening aid only — see the disclaimers inside each tool output.</footer>
</body></html>
""",
        encoding="utf-8",
    )


def main() -> int:
    sections, audit, http_events = asyncio.run(run_demo())
    write_report(sections, audit, http_events)
    total_checks = sum(len(outcomes) for *_rest, outcomes, _e in sections)
    total_passed = sum(1 for *_rest, outcomes, _e in sections for _, ok in outcomes if ok)
    print(f"\n{total_passed}/{total_checks} checks passed — report written to {REPORT_PATH}")
    return 0 if total_passed == total_checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
