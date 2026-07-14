<p align="center">
  <img src="docs/assets/nepa-mcp-toolkit.png" alt="PermitAI — NEPA MCP Toolkit" width="620">
</p>

<p align="center">
  <strong>Federal environmental data and regulatory research for AI-assisted NEPA workflows</strong>
</p>

<p align="center">
  <strong>Works with</strong><br>
  <a href="#configure-an-mcp-client"><img alt="Codex MCP client" src="docs/assets/badges/codex-client-config.svg"></a>
  <a href="#codex-plugin"><img alt="Codex plugin" src="docs/assets/badges/codex-plugin.svg"></a>
  <a href="#configure-an-mcp-client"><img alt="Claude Code client configuration" src="https://img.shields.io/badge/Claude_Code-MCP_Client-D97757?style=flat-square&amp;logo=anthropic&amp;logoColor=white"></a>
  <a href="#configure-an-mcp-client"><img alt="VS Code client configuration" src="docs/assets/badges/vscode-mcp-client.svg"></a>
</p>

<p align="center">
  <strong>Built with</strong><br>
  <a href="https://www.python.org/"><img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="https://gofastmcp.com/"><img alt="FastMCP 3.4.4" src="https://img.shields.io/badge/FastMCP-3.4.4-009688?style=flat-square"></a>
  <a href="https://docs.pydantic.dev/"><img alt="Pydantic 2.12+" src="https://img.shields.io/badge/Pydantic-2.12%2B-E92063?style=flat-square&amp;logo=pydantic&amp;logoColor=white"></a>
  <a href="https://shapely.readthedocs.io/"><img alt="Shapely 2.0+" src="https://img.shields.io/badge/Shapely-2.0%2B-2F6F3E?style=flat-square"></a>
  <a href="LICENSE"><img alt="ISC License" src="https://img.shields.io/badge/License-ISC-F4B942?style=flat-square"></a>
</p>

NEPA MCP is the Model Context Protocol (MCP) server layer of the PermitAI
toolkit. It gives AI agents structured access to federal environmental,
regulatory, biological, cultural, socioeconomic, and jurisdictional data used
in NEPA screening and permitting research.

The repository provides 18 independent domain servers, an installable
`nepa-mcp` command, client-configuration helpers, and an optional Codex plugin.
Each server exposes structured responses directly to the connected MCP client.

**Explore capabilities:** Browse the [MCP Tool Catalog](docs/mcp-tool-catalog.md)
for all 18 servers and 43 tools at a glance.

> [!IMPORTANT]
> NEPA MCP is a screening and research aid. It does not make legal or agency
> determinations, replace consultation with agencies or Tribes, or guarantee
> that an upstream dataset is complete or current. Confirm material findings
> against authoritative records and current requirements.

## Quick Start

### Prerequisites

- Python 3.12 or newer
- [`pipx`](https://pipx.pypa.io/) for an isolated installation
- Git

Clone the public repository and install the runtime:

```bash
git clone https://github.com/sarthakchat/nepa-mcp-server.git
cd nepa-mcp-server
pipx install .
```

Verify the installation and list the available domains:

```bash
nepa-mcp doctor
nepa-mcp list-servers
```

Start an individual server over stdio:

```bash
nepa-mcp server ipac
nepa-mcp server cfr
```

Individual servers are the recommended pattern for MCP clients. An aggregate
proxy is also available for testing or workflows that deliberately want every
tool behind one connection:

```bash
nepa-mcp server all
```

If `nepa-mcp` is already installed from another checkout or an older local
build, replace it with this checkout:

```bash
pipx install --force .
```

## Configure an MCP Client

The repository includes examples for Claude Code (`.mcp.json`), VS Code
(`.vscode/mcp.json`), and Codex (`config.template.toml`). Each example registers
the 18 domains as separate MCP servers.

The CLI can merge those entries into an existing client configuration:

```bash
nepa-mcp configure claude
nepa-mcp configure vscode
nepa-mcp configure codex
```

Use `--dry-run` to preview the result or `--path` to choose a different file.
Unrelated MCP entries are preserved, and an existing file receives a one-time
`.nepa-mcp.bak` backup.

## Codex Plugin

The repository contains a local Codex marketplace and a `nepa-mcp` plugin. The
plugin registers all 18 domain servers and includes the `nepa-screening` skill.
After installing the Python runtime, run:

```bash
codex plugin marketplace add "$(pwd)"
codex plugin add nepa-mcp@nepa-mcp-local
```

Start a new Codex task after installing or updating the plugin so the new MCP
tools and skill are loaded.

## Credentials

Most servers use public APIs without credentials. Two integrations support
optional credentials:

| Server | Environment variables |
|---|---|
| `census` | `CENSUS_API_KEY` |
| `epa_aqs` | `EPA_AQS_EMAIL`, `EPA_AQS_API_KEY` |

Set the variables in the shell or create a private per-user credential file:

```bash
nepa-mcp configure
nepa-mcp doctor
```

`configure` creates a template only when one does not already exist and prints
its location. The default is the operating system's per-user configuration
directory under `nepa-mcp/credentials.env`; override it with
`NEPA_MCP_CONFIG_FILE`. Environment variables take precedence over the file.
Credentials are not copied into MCP client or plugin configuration, and
`doctor` reports only whether each value is present.

## Server Inventory

| Server | Purpose |
|---|---|
| `blm` | BLM land use plans, wilderness areas, and national monuments |
| `census` | Census ACS socioeconomic indicators |
| `cfr` | CFR citations and structure, Federal Register history, and executive orders |
| `efh` | NOAA Essential Fish Habitat and HAPC screening |
| `epa_aqs` | EPA air-quality monitoring and NAAQS screening |
| `esa_ranges` | NOAA ESA-listed species ranges |
| `fema_nfhl` | FEMA flood zones, levees, and water areas |
| `gbif` | GBIF species occurrences and biodiversity data |
| `gis` | Region-of-interest geometry, GeoJSON, and area utilities |
| `ipac` | USFWS IPaC species, critical habitat, and migratory birds |
| `nepa_assist` | EPA NEPAssist environmental screening |
| `noaa` | NOAA West Coast Region critical habitat |
| `nrhp` | National Register of Historic Places properties |
| `padus` | USGS PAD-US protected areas, ownership, and management records |
| `pcsrf` | NOAA species, habitat, and recovery-program datasets |
| `tigerweb_counties` | Census TIGERweb county intersections |
| `tribal` | Census AIANNHA tribal lands |
| `usace` | USACE regulatory districts and wetland regions |

## Geographic Inputs and Data Behavior

- Geographic screening tools currently accept a WGS84 latitude, longitude,
  and point-buffer distance. Project-polygon input is not yet supported.
- Tool schemas constrain point buffers to 0.1–100 miles. The default is 25
  miles unless a tool documents another value.
- `esa_ranges` combines both complementary NOAA `Ranges_dice` layers. Layer 1
  covers Washington, Idaho, Oregon, and transboundary fish ranges; Layer 2
  covers California and southern Oregon.
- `efh` uses the public services behind NOAA's EFH Mapper for HAPC, general EFH,
  Pacific salmon watersheds, and species or management-unit screening.
- `noaa` consolidates diced critical-habitat fragments by listed entity while
  preserving distinct named habitat units.
- Empty NOAA West Coast and PCSRF-project results outside their expected
  service geography include a coverage warning.
- Upstream request failures and partial-layer failures are returned as
  warnings; they are not presented as evidence that a resource is absent.

## Development

[`uv`](https://docs.astral.sh/uv/) is required only for source development and
testing. From the repository root:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q .
uv run pytest -q
```

Most tests do not require credentials. To exercise the optional Census or EPA
AQS integrations, use `uv run nepa-mcp configure` or export the variables
listed above. A repository `.env` file is not loaded automatically; opt into it
with `uv run --env-file .env <command>`.

Each domain follows the same basic layout:

```text
server_name/
├── requirements.txt
├── server.py
└── src/
    ├── apis/
    └── core/
```

Shared runtime, HTTP, validation, and ArcGIS utilities live in
`nepa_mcp_common/`. The root `pyproject.toml` builds the installable distribution;
individual `requirements.txt` files remain available for standalone deployment
packaging.

Inspect a server's MCP contract with FastMCP:

```bash
uv run fastmcp inspect cfr/server.py:mcp --skip-env
```

The test suite checks server startup and discovery, tool-schema readability,
offline invalid-argument handling, shared utilities, and distribution contents.

## Data Sources and Licensing

The [data-source inventory](docs/mcp-data-source-licenses.md) records
the source agencies, endpoints, authentication requirements, license signals,
and release notes for the current server inventory. Upstream data remains
subject to each source's terms and authoritative-use guidance.

## Contributing

Issues and pull requests are welcome. Please keep changes scoped to the public
server runtime, include tests for behavioral changes, and run the development
checks above before opening a pull request.

## License

The repository's source code is available under the [ISC License](LICENSE).

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
