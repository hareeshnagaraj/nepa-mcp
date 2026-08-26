# ACRES Brownfields Map Composer overlay spec

This is a short integration spec for adding an ACRES Brownfields point overlay to `map_composer` without changing the existing `epa_acres` server contract.

## User workflow

Input:

- ROI center latitude and longitude in WGS84 decimal degrees.
- ROI buffer in miles.
- Optional output basename supplied by the operator-controlled Map Composer artifact path logic.

Processing:

1. Call `epa_acres.get_epa_acres_properties_in_roi` with the ROI center and buffer.
2. Sort and preserve the returned properties in nearest-first order, as the ACRES server already does.
3. Add point markers for ACRES properties that include usable latitude and longitude.
4. Label the nearest few markers with property name, city/state, distance from center, ACRES property ID, and the Cleanups in My Community source URL when present.
5. Store the ACRES source caveat in map metadata and in the layer/source panel.
6. Preserve Map Composer's existing per-layer status model: `ok`, `empty`, `partial`, or `failed`.

Guardrail: sites are labeled "EPA ACRES Brownfields grant-program property records", never "contaminated".

## Output

The tool should return:

- A map image or interactive map artifact with ACRES point markers.
- A JSON summary containing the ROI center, buffer, ACRES total, nearest labeled records, layer status, warnings, and source metadata.

Suggested JSON summary shape:

```json
{
  "layer": "epa_acres_brownfields",
  "label": "EPA ACRES Brownfields grant-program property records",
  "status": "ok",
  "roi": {"latitude": 40.455, "longitude": -79.99, "buffer_miles": 5.0},
  "total": 190,
  "rendered_markers": 190,
  "nearest_labeled": [
    {
      "name": "RIVER AVE REUSE PLAN",
      "city": "PITTSBURGH",
      "state": "PA",
      "distance_miles": 0.077,
      "acres_property_id": "251084",
      "source_url": "https://ordspub.epa.gov/ords/cimc/f?p=CIMC:31::::31:P31_ID:..."
    }
  ],
  "source": {
    "publisher": "EPA",
    "dataset": "ACRES Brownfields grant-program property records",
    "caveat": "ACRES contains EPA Brownfields grant-program property records reported by grantees; it is not a complete inventory of brownfields or contaminated sites."
  },
  "warnings": []
}
```

## Reviewer caveats

- ACRES is grant-reported program data, not a contaminated-site inventory.
- A nearby ACRES record is a screening flag for follow-up, not a determination that land is contaminated, available, or suitable for development.
- An empty ACRES result is not evidence that the area is free of brownfields or contamination.
- Confirm material findings with environmental site assessments and authoritative federal, state, Tribal, and local records.
