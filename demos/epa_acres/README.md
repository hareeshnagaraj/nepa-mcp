# epa_acres demo

Standalone demonstration client for the `epa_acres` server added to
[pnnl/nepa-mcp](https://github.com/pnnl/nepa-mcp) (issue #21, branch
`epa-acres-server`). The client and documentation are tracked; generated
`report.html` and `audit.jsonl` remain ignored.

What it proves, end to end:

1. **Real client launch** — the server is started over MCP stdio with
   `nepa-mcp server epa_acres`, the exact command every shipped client config
   (`.mcp.json`, VS Code, Codex) uses, with no in-process shortcuts.
2. **Contract discovery** — `tools/list` shows the single tool, its documented
   argument bounds/defaults, and its read-only annotations.
3. **Live screening** — three scenarios against the live EPA Envirofacts
   Brownfields layer: a dense urban ROI (exercises the 100-record listing cap),
   a small neighborhood ROI (complete listing), and a rural ROI that returns
   zero records with the coverage caveats intact.
4. **Validation** — an out-of-range latitude is rejected with an actionable
   `ToolError` before any upstream call.
5. **Exact upstream flow** — runtime instrumentation records the Esri
   `GeometryServer/buffer` GET and EPA Brownfields layer-5 query POST, including
   paging fields, status, and timing. It also proves validation makes zero HTTP
   requests.

Each scenario is verified against lightweight expectations; the run prints a
pass/fail summary and writes `report.html` with the full rendered tool output
plus separate tables for demo-issued MCP operations and actual upstream HTTP
requests. `audit.jsonl` preserves the full request values for provenance; the
HTML summarizes large geometry payloads for readability. Client-internal MCP
initialization is not represented as a raw wire capture.

## Run it

From the repository root, with the dev environment installed
(`uv sync --all-groups`):

```bash
uv run python demos/epa_acres/demo.py
```

Then open `demos/epa_acres/report.html`. To run against a different checkout,
set `NEPA_MCP_REPO=/path/to/nepa-mcp`.

Exit code is nonzero if any check fails. Network access to
`geopub.epa.gov` and `utility.arcgisonline.com` is required.
