# Point-Buffer Spatial Area Rollout — LLM Handoff

## Copy/paste prompt for the next LLM

You are continuing work in the `nepa-mcp-server` repository on branch
`codex/spatial-area-pilot`.

Read this entire handoff, then inspect `git status`, `git diff --check`, and the
complete diff. Preserve all existing work. The root `AGENTS.md` is an unrelated
untracked user file; do not stage, edit, or remove it unless the user explicitly
asks.

The approved scope is deliberately narrow:

- keep every MCP input as WGS84 latitude, longitude, and point-buffer miles;
- compute accurate unioned feature area inside that point-buffer ROI;
- retain upstream whole-feature area separately as provenance;
- report status, completeness, and warnings;
- do not add project-polygon inputs, map composition, file exports, or arbitrary
  output paths.

The implementation covers NOAA critical habitat, both ESA ranges layers,
PCSRF generalized critical habitat and Atlantic salmon EFH/HAPC, and the EFH
Mapper species/management-unit layer. HAPC presence, general EFHA presence,
salmon HUC-8 presence, PCSRF projects, species-range presence, and line-length
semantics remain unchanged.

Before making further changes, run the existing tests. If a defect is found,
add a focused regression test first. Report confirmed evidence separately from
recommendations.

## Repository state

- Repository: `nepa-mcp-server`
- Branch: `codex/spatial-area-pilot`
- Changes are currently uncommitted.
- The private comparison repository under `/private/tmp` is reference material
  only; this implementation does not depend on it.

Start with:

```bash
git branch --show-current
git status --short
git diff --check
git diff
```

## Shared spatial implementation

`nepa_mcp_common/spatial.py` provides
`clipped_union_area_from_esri_geometries()` and structured result types.

It:

- accepts ESRI polygon geometry dictionaries;
- reconstructs shells, holes, nested rings, and multipart polygons;
- recognizes EPSG WKIDs and WKT/WKT2 CRS metadata;
- transforms source geometry to WGS84 with PyProj;
- handles long edges, high latitudes, and antimeridian-crossing rings;
- projects to a local Lambert azimuthal equal-area CRS;
- repairs polygon topology, unions fragments, and clips once to the ROI;
- returns unrounded square meters plus explicit conversion helpers;
- distinguishes `ok`, `no_overlap`, `no_geometry`, `invalid_roi`, and
  `invalid_geometry`;
- reports input/used geometry counts, completeness, and warnings.

An `ok` result can still have `complete=false` if any fragment was skipped.
Callers must preserve that distinction.

`nepa_mcp_common/arcgis.py` also supports `out_sr`. Response-level CRS metadata
is copied onto individual geometries when ArcGIS omits it there. Existing POST
queries, pagination, feature caps, truncation warnings, and null-feature
handling remain active.

## Area-enabled server behavior

### NOAA critical habitat

For polygon records:

- `area_sqkm`: unioned area inside the ROI;
- `source_area_sqkm`: upstream whole-feature area total;
- `area_status`, `area_complete`, `area_warnings`: calculation provenance.

The line layer continues to report source `lengthkm`; line clipping is out of
scope.

### ESA ranges

Both complementary Ranges_dice layers request feature geometry in EPSG:4326.
Fragments are grouped by listed entity and HUC-12 before union/clip.

Each record uses:

- `area_sqkm`: area inside the ROI;
- `source_area_sqkm`: source watershed-area total;
- the common status/completeness/warning fields.

Layer 2 still wins when both layers produce the same listed-entity/HUC key.
Such a collision is conservatively marked incomplete because distinct Layer 1
geometry may have been discarded. Repeated Layer 1 population rows use the
maximum reported whole-HUC source area instead of multiplying that attribute.

### PCSRF data services

Generalized critical-habitat polygons use `area_sqkm` and
`source_area_sqkm`. Critical-habitat lines retain the pre-existing
source-coordinate length estimate, are explicitly marked as not ROI-clipped,
and are not treated as verified geodesic kilometers.

Atlantic salmon EFH/HAPC polygons use:

- `area_acres`: unioned area inside the ROI;
- `area_sq_units`: retained raw service attribute, whose coordinate-square unit
  is not relabeled as acres;
- the common status/completeness/warning fields.

PCSRF projects and the all-species range tool are unchanged.

### EFH Mapper

Only the species/management-unit query (`get_efh_hms_cps_groundfish`) requests
measurement geometry. Grouped records use:

- `acres`: unioned area inside the ROI;
- `source_acres`: upstream whole-feature acreage;
- the common status/completeness/warning fields.

HAPC, general EFHA, and salmon HUC-8 tools retain presence-only semantics and do
not request geometry for area measurement.

## Query and completeness rules

- Measurement queries set `return_geometry=true`, `outSR=4326`, and disable
  query-ROI simplification.
- Non-measurement paths do not request feature geometry.
- Duplicate or overlapping fragments are unioned before clipping.
- Missing/invalid geometry never becomes zero area.
- ArcGIS truncation forces `area_complete=false` and adds an understatement
  warning.
- Reaching the feature cap exactly is complete when ArcGIS reports no remaining
  records; only true excess/transfer-limit cases are marked truncated.
- Per-record geometry warnings are promoted to the top-level tool warning list.
- A true non-overlap is represented by status `no_overlap` and area `0.0`.
- Line features do not receive polygon-area values, and legacy line estimates
  are not presented as clipped measurements.

## Dependencies and packaging

- Root dependencies include `pyproj>=3.7.0` and Shapely.
- `efh`, `esa_ranges`, `noaa`, and `pcsrf` standalone requirements also include
  PyProj and Shapely.
- `nepa_mcp_common.spatial` is not re-exported from `nepa_mcp_common.__init__`,
  keeping non-spatial common imports independent of PyProj.
- Distribution tests enforce both dependency isolation and the four standalone
  PyProj declarations.

## Tests and verification

Focused hermetic coverage is in:

- `tests/test_spatial_common.py`
- `tests/test_point_buffer_area_rollout.py`
- `tests/test_five_server_updates.py`
- `tests/test_arcgis_common.py`
- `tests/test_distribution.py`

The tests cover holes, multipart features, duplicates, missing and invalid
geometry, CRS conversion, antimeridian/high-latitude cases, truncation,
geometry-query options, line behavior, formatter provenance, and legacy parser
compatibility.

The current worktree has passed:

```text
138 pytest tests
Ruff check for the full repository
Ruff formatting check for all 125 Python files
compileall for nepa_mcp_common, noaa, esa_ranges, pcsrf, and efh
git diff --check
uv lock --check
wheel build
```

The verified wheel is:

```text
/private/tmp/nepa-mcp-build-point-buffer/nepa_mcp-0.1.0-py3-none-any.whl
```

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m compileall -q nepa_mcp_common noaa esa_ranges pcsrf efh
git diff --check
uv lock --check
uv build --wheel --out-dir /private/tmp/nepa-mcp-build-spatial-review
```

## Live verification

On July 13, 2026, one-mile point-buffer smoke checks ran successfully against
the live public services. Every returned area record had status `ok`, was
complete, stayed within the theoretical ROI area (with a one-percent numerical
tolerance), and produced no service warning or error.

| Service/query | Records | Latency |
| --- | ---: | ---: |
| NOAA critical habitat, Monterey | 6 | 1.576 s |
| ESA species ranges, Monterey | 1 | 0.865 s |
| EFH HMS/CPS/Groundfish, Monterey | 14 | 72.688 s |
| PCSRF critical habitat, Monterey | 6 | 0.955 s |
| PCSRF Atlantic salmon EFH, Maine | 1 | 0.812 s |

The earlier NOAA payload comparison remains relevant: requesting geometry
increased the Monterey response from roughly 518 bytes to 152,307 bytes. The
live EFH result also demonstrates that geometry-heavy calls can be materially
slower even at a one-mile buffer.

Before production merge, add medium- and large-buffer samples where each
dataset has coverage. Record latency, feature count, vertex count, payload size,
truncation, warnings, and whether every complete clipped area is no greater
than the ROI area within numerical tolerance.

Do not weaken these acceptance gates:

- no missing or invalid fragment may be reported complete;
- truncated responses must be visibly incomplete;
- source and ROI area must remain separately labeled;
- no tool name, input schema, or Markdown return-type regression;
- empty-result coverage warnings must remain intact;
- 100-mile cases must stay within an agreed latency and memory budget.

## Compatibility note

For NOAA, ESA ranges, and PCSRF critical-habitat polygon records, the existing
area field now means area inside the ROI. The former upstream attribute is
retained in a `source_*` field. EFH Mapper follows the same pattern for `acres`.
This is an intentional semantic change for direct Python consumers; MCP tools
continue to return Markdown and explicitly label both values.

## Files in scope

```text
README.md
docs/spatial-area-pilot-handoff.md
nepa_mcp_common/arcgis.py
nepa_mcp_common/spatial.py
noaa/requirements.txt
noaa/server.py
noaa/src/apis/noaa_api.py
esa_ranges/requirements.txt
esa_ranges/server.py
esa_ranges/src/apis/esa_ranges_api.py
pcsrf/requirements.txt
pcsrf/server.py
pcsrf/src/apis/pcsrf_api.py
efh/requirements.txt
efh/server.py
efh/src/apis/efh_api.py
pyproject.toml
uv.lock
tests/test_arcgis_common.py
tests/test_distribution.py
tests/test_five_server_updates.py
tests/test_point_buffer_area_rollout.py
tests/test_spatial_common.py
```

Treat other changes as unrelated unless the user explicitly expands scope.
