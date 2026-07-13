# nepa-mcp-server

Stateless MCP servers for NEPA environmental permitting workflows. Each
top-level domain directory is registered as an independent MCP server and
returns data inline through tools instead of writing CSV exports or
repository-local output files. The domain servers share common runtime and
ArcGIS utilities from `nepa_mcp_common/`.

This repository is intentionally flat. The older monorepo-style `mcp_servers/`,
demo, agent, deployment-guide, and helper-script folders are not part of this
public surface because they include extra local workflows that are not needed by
agent-facing servers.

The installable distribution exposes one command, `nepa-mcp`. Each domain can
run as an independent MCP server. An optional aggregate proxy remains available
for testing and workflows that deliberately want one combined connection.

## Layout

Each server directory follows the same basic shape:

```text
server_name/
├── requirements.txt
├── server.py
└── src/
    ├── apis/
    └── core/
```

## Prerequisites

- Python 3.12 or newer
- `pipx` for an isolated end-user installation
- `uv` only when developing or testing the source checkout
- Codex CLI only when installing the optional Codex plugin

## Development

This section is for contributors modifying the source. It is not required to
install or use the MCP servers. From the repository root:

```bash
uv sync --all-groups
uv run fastmcp version
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q .
uv run pytest -q
```

Most development and test commands do not require credentials. To exercise the
optional Census or EPA AQS integrations, create the same owner-only credential
file used by an installed runtime:

```bash
uv run nepa-mcp configure
uv run nepa-mcp doctor
```

Alternatively, export the documented variables in the shell. A repository
`.env` file is not loaded automatically; use `uv run --env-file .env <command>`
only when you deliberately want that development behavior.

## Install and Run

Install the runtime in an isolated environment with `pipx`:

```bash
pipx install .
nepa-mcp doctor
nepa-mcp list-servers
```

If another checkout or an older local build already installed the
`nepa-mcp` pipx environment, replace it with this repository explicitly:

```bash
pipx install --force .
```

Use `--force` here instead of `pipx upgrade nepa-mcp`: an upgrade normally
retains the original package source, while this command switches the installed
runtime to the current checkout.

Start one domain server, which is the pattern used by the Codex plugin and
shipped client configurations:

```bash
nepa-mcp server ipac
nepa-mcp server cfr
```

The optional aggregate command is available for testing or clients that
explicitly want all tools behind one MCP connection:

```bash
nepa-mcp server all
```

The aggregate server uses FastMCP subprocess proxies. Each child keeps its own
top-level `src` package, so the flat server layout does not create Python module
collisions.

## Credentials

Most servers use public APIs without credentials. Census and EPA AQS use these
optional environment variables:

| Server | Variables |
|--------|-----------|
| `census` | `CENSUS_API_KEY` |
| `epa_aqs` | `EPA_AQS_EMAIL`, `EPA_AQS_API_KEY` |

Set them in the shell or create an owner-only user credential template:

```bash
nepa-mcp configure
nepa-mcp doctor
```

`configure` creates the template only when it does not already exist and prints
its location. Open that file and fill only the optional credentials you use.
The default is the operating system's standard per-user configuration location
under `nepa-mcp/credentials.env`, with owner-only permissions. Override it with
`NEPA_MCP_CONFIG_FILE`. Existing environment variables take precedence over the
file. Credentials are not written to MCP client configuration or plugin files,
and `doctor` reports only whether each variable is present.

## Client Configuration

The repository includes project examples for Claude Code (`.mcp.json`), VS Code
(`.vscode/mcp.json`), and Codex (`config.template.toml`). Each file registers all
18 domains as separate MCP servers. The installed CLI can merge those independent
entries into a client configuration:

```bash
nepa-mcp configure claude
nepa-mcp configure vscode
nepa-mcp configure codex
```

Use `--dry-run` to print the result or `--path` to select another file. Existing
unrelated server entries are preserved and an existing file receives a one-time
`.nepa-mcp.bak` backup.

## Codex Plugin

The repository contains a local Codex marketplace and the `nepa-mcp` plugin.
The plugin registers 18 independent MCP servers, each running
`nepa-mcp server <name>`. Install the Python runtime first, then add the
repository marketplace:

```bash
pipx install .
codex plugin marketplace add "$(pwd)"
codex plugin add nepa-mcp@nepa-mcp-local
```

Start a new Codex task after installing or updating the plugin so the MCP tools
and `nepa-screening` skill are loaded from the new plugin version.

For an existing checkout, reinstall both layers after pulling changes:

```bash
pipx install --force .
codex plugin add nepa-mcp@nepa-mcp-local
```

When developing the plugin itself, refresh the manifest's Codex cachebuster
before reinstalling so Codex creates a new cached version. Use the Codex
`plugin-creator` update helper for that step rather than editing marketplace
configuration by hand. A fresh Codex task is still required after reinstalling.

Servers use standalone FastMCP 3.x via `from fastmcp import FastMCP`.
The official `mcp` SDK may still appear in `uv.lock` and `fastmcp version`
output because FastMCP depends on it for the underlying protocol layer.
Tool contracts use FastMCP's docstring parsing for natural-language tool and
argument descriptions, plus `typing.Annotated`/`pydantic.Field` constraints for
machine-readable JSON Schema ranges. Data-query tools are annotated as
read-only, non-destructive, idempotent, and open-world.

FastMCP CLI inspection can be used against a server object:

```bash
uv run fastmcp inspect cfr/server.py:mcp --skip-env
```

The pytest suite includes FastMCP contract checks for startup/tool discovery,
schema readability, and offline invalid-argument handling across all servers.

The root `pyproject.toml` builds the `nepa-mcp` wheel and also supports local
development and cross-server checks. Individual server `requirements.txt` files
remain in place for standalone deployment packaging.

## Server Inventory

| Server | Purpose |
|--------|---------|
| `blm` | BLM land use plans, wilderness areas, national monuments |
| `census` | Census socioeconomic data from ACS |
| `cfr` | CFR citation resolution, structure browsing, history, Federal Register, and EO lookup |
| `efh` | NOAA Essential Fish Habitat and HAPC screening |
| `epa_aqs` | EPA air quality monitoring and NAAQS data |
| `esa_ranges` | NOAA ESA-listed species ranges |
| `fema_nfhl` | FEMA flood zones, levees, and water areas |
| `gbif` | GBIF species occurrences and biodiversity data |
| `gis` | ROI generation, GeoJSON, and area utilities |
| `ipac` | USFWS IPaC species, critical habitat, and migratory birds |
| `nepa_assist` | EPA NEPA Assist environmental screening |
| `noaa` | NOAA West Coast Region critical habitat |
| `nrhp` | National Register of Historic Places properties |
| `padus` | USGS PAD-US protected-area ownership and management records |
| `pcsrf` | NOAA all-species ranges, critical habitat snapshot, Atlantic salmon EFH/HAPC, and PCSRF recovery projects |
| `tigerweb_counties` | Census TIGERweb county identification |
| `tribal` | Census AIANNHA tribal lands for consultation |
| `usace` | USACE regulatory districts and wetland regions |

## Geographic Inputs and Data Behavior

- The geographic screening tools currently accept a WGS84 latitude, longitude,
  and point-buffer distance. Project-polygon input is not supported.
- Tool schemas constrain point buffers to 0.1–100 miles. The default is 25
  miles unless a tool documents another behavior.
- `esa_ranges` combines both complementary NOAA `Ranges_dice` layers: Layer 1
  covers Washington, Idaho, Oregon, and transboundary fish ranges; Layer 2
  covers California and southern Oregon.
- `efh` uses the public services behind NOAA's EFH Mapper for HAPC, general EFH,
  Pacific salmon watersheds, and EFH species/management-unit screening.
- `noaa` consolidates diced critical-habitat fragments by listed entity while
  preserving distinct named habitat units.
- Empty NOAA West Coast and PCSRF-project responses outside their expected
  service geography include an explicit coverage warning. Queries still run;
  the warning is added only after an empty response.
- Upstream request failures and partial-layer failures are reported as warnings.
  They are not presented as evidence that a resource is absent.

## Public Release References

- [MCP data source licenses](technical-docs/mcp-data-source-licenses.md) tracks source agencies, endpoints, auth requirements, license signals, and release-risk notes for the current server inventory.
- [TestPyPI publishing](technical-docs/testpypi-publishing.md) documents package upload, verification, and the one-package/18-independent-server distribution model.

## License

This project is available under the [ISC License](LICENSE), the permissive
license form commonly associated with OpenBSD.

## Citation

If you use NEPA MCP in research, environmental assessments, or other scientific
or technical publications, please cite it as:

```bibtex
@software{nepa_mcp,
  author       = {Chaturvedi, Sarthak and Chintalapati, Renuka and Nally, Dan and Parkar, Mike and Munikoti, Sai and Horawalavithana, Sameera},
  title        = {NEPA MCP: Independent MCP Servers for NEPA Environmental Screening},
  year         = {2026},
  institution  = {Pacific Northwest National Laboratory},
  url          = {https://github.com/sarthakchat/nepa-mcp-server},
  version      = {0.1.0},
  license      = {ISC}
}
```
