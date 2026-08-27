# /extension/adapters/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 1 Critical Path | **Owner:** TBD

Server-served JSON adapter files — one per ATS family.

Each adapter maps a specific job board's DOM structure to the extension's field classification system.
Adapters are versioned data, not code — a broken selector is fixed server-side in minutes, not a store review cycle.

## Planned adapters (Phase 1–2)

| File | ATS | Notes |
|------|-----|-------|
| `greenhouse.json` | Greenhouse (boards.greenhouse.io) | Phase 1 target |
| `lever.json` | Lever (jobs.lever.co) | Phase 2 |
| `ashby.json` | Ashby (jobs.ashbyhq.com) | Phase 2 |

## Adapter schema (per field mapping)

```
{
  "ats_family": "greenhouse",
  "version": "1.0.0",
  "selectors": { ... },
  "field_aliases": { ... },
  "attestation_overrides": [ ... ]
}
```

> Workday, Taleo, iCIMS — Phase 4 (multi-page wizard + iframe coordination required).
