# NEPA-MCP Server Test Suite Report

> [!NOTE]
> This report is a historical snapshot from before the Map Composer server was
> added. The current toolkit contains 19 MCP servers; see the generated
> [MCP Tool Catalog](mcp-tool-catalog.md) for the live inventory.

_Repository: `nepa-mcp-server` · Branch: `add-five-tier-server-test-suites`_
_Scope: categorized test coverage added for all 18 MCP servers, plus repo-health / static-analysis checks._

## Overview

Each of the 18 servers received a five-category test suite (unit, integration,
resilience, security, performance), following one shared template so the
categories mean the same thing across servers. A separate repo-health tier
encodes the non-functional checks (filesystem hygiene, secrets, dependency
pinning, README, and the ruff / mypy / pip-audit static-analysis gates).

All tests are **hermetic** — every upstream API call (ArcGIS FeatureServers,
eCFR / Federal Register, EPA AQS, GBIF, IPaC, Census, FEMA NFHL) is mocked, so
the suite is fast (~10 s), deterministic, and safe to run in CI with no network
or credentials.

**Result: 1082 tests, all passing** (933 new server tests + 11 repo-health +
the repository's pre-existing 138).

## What each category verifies

| Category | What it checks |
|---|---|
| **Unit** | Pure logic in isolation — response parsing, field mapping, dedup/grouping, area-clipping math, and the Markdown formatters. Upstream I/O mocked. |
| **Integration** | The full tool → API → formatter path driven through a real `fastmcp.Client`, asserting the Markdown a client actually receives, plus tool registration and input-validation rejection at the tool boundary. |
| **Resilience** | Failure modes — upstream timeouts / connection errors / HTTP 4xx-5xx, malformed or null payloads, truncated result sets, and partial (one-layer-down) failures. Asserts the server's *actual* degrade-or-raise behavior. |
| **Security** | Input validation (coordinate/buffer bounds, NaN/inf, non-numeric), no hardcoded secrets in source, public-endpoint URLs, and error messages that don't leak internal paths or credentials. |
| **Performance** | Algorithmic scaling on synthetic data — dedup collapse, pagination caps, and bounded parse/format time (hermetic, no live latency). |

## Results by category

| Category | Tests |
|---|---|
| Unit | 307 |
| Integration | 132 |
| Resilience | 152 |
| Security | 269 |
| Performance | 73 |
| **Server-suite subtotal** | **933** |
| Repo health / static analysis | 11 |
| Pre-existing suite (unchanged) | 138 |
| **Total passing** | **1082** |

## Results by server

| Server | Tests | | Server | Tests |
|---|---:|---|---|---:|
| blm | 50 | | ipac | 46 |
| census | 54 | | nepa_assist | 60 |
| cfr | 77 | | noaa | 54 |
| efh | 55 | | nrhp | 46 |
| epa_aqs | 57 | | padus | 39 |
| esa_ranges | 57 | | pcsrf | 61 |
| fema_nfhl | 49 | | tigerweb_counties | 43 |
| gbif | 51 | | tribal | 45 |
| gis | 41 | | usace | 48 |

## Repo-health & static-analysis scorecard

| Check | Result | Detail |
|---|---|---|
| **Ruff** (whole repo) | PASS | 0 issues |
| **pip-audit** (dependencies) | PASS | No known vulnerabilities |
| **mypy** — `nepa_mcp_common` core | PASS | No real type errors (shapely ships no stubs; `--ignore-missing-imports`) |
| **mypy** — `cfr_api.py` (sampled) | NOTE | ~29 non-breaking annotation items; the repo does not currently adopt mypy, so this is optional cleanup |
| `.gitignore` / `.env.example` | PASS | Sensitive paths excluded; env template present |
| `pyproject.toml` + `uv.lock` | PASS | Dependencies declared and locked |
| Area-server geometry deps | PASS | efh / esa_ranges / noaa / pcsrf declare pyproj + shapely |
| Secrets scan (18 servers) | CLEAN | No hardcoded secret literals; credentials via env only |
| README completeness | PASS | Quick Start, Configure, Server Inventory, License, Citation present |

**Verdict: READY WITH NOTES.** Clean lint, clean dependency audit, clean
secrets, type-clean core. The only open item is the optional cfr mypy
annotation cleanup, relevant only if mypy is later adopted into CI.

## Behaviors documented as-is (found, not "fixed")

Testing against the real code surfaced several behaviors worth recording. These
are asserted as the current contract, not changed:

- **NRHP outage vs. empty:** when *both* NRHP layers fail, the tool returns the
  same empty shape as a genuine no-hit screen; the outage is signalled **only in
  `warnings`** ("results are unavailable, not a no-hit finding"), not via an
  `error` field. A consumer that ignores warnings cannot distinguish a full
  outage from a clean negative screen.
- **PAD-US null features:** a successful response whose `features` key is `null`
  raises `TypeError` (the parser iterates it without a guard). TIGERweb counties,
  by contrast, coerces the same case to an empty result via the shared query
  layer.
- **Area vs. source provenance (efh / pcsrf / noaa / esa_ranges):** ROI-clipped
  area is derived from feature geometry and is independent of the upstream
  `ACRES` / `areasqkm` attribute, so "clipped < source" is not a valid
  invariant; the tests assert provenance separation and that duplicate fragments
  union rather than inflate.
- **Degrade-vs-raise varies by server:** blm / efh / pcsrf / gbif / tribal
  catch upstream query errors and return empty-plus-warning; usace / gis / ipac
  / padus / tigerweb propagate them. Each suite asserts the server's actual mode.

## Running the suite

```bash
# full suite
.venv/bin/python -m pytest -q

# one category across all servers
.venv/bin/python -m pytest tests/test_*_security.py -q

# one server, all categories
.venv/bin/python -m pytest tests/test_usace_*.py -q

# repo-health / static-analysis tier (ruff/mypy/pip-audit gated — skip if absent)
.venv/bin/python -m pytest tests/test_repo_health.py -q
```

A shared `tests/conftest.py` fixture snapshots and restores `ArcGISService`
methods around every test, so the suites are order-independent whether run
individually or together.
