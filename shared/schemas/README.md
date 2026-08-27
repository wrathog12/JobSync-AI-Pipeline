# /shared/schemas/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 0 Foundation | **Owner:** TBD

Canonical JSON Schema definitions — the single source of truth.

## Planned files

| File | Schema | Maps to |
|------|--------|---------|
| `profile.schema.json` | Layer 1 canonical entity schema (§3.2) — Person, Employment, Education, Project, Skill, Credential, Preference, Authorization | Pydantic (server) + TypeScript (extension) |
| `evidence_chunk.schema.json` | Layer 2 evidence chunk with provenance fields (§3.3) — entity_id, employer_id, employer_name, date_range, competency_tags, skill_ids, confidence | Pydantic + TypeScript |
| `fill_payload.schema.json` | Extension → Server request payload: page_url, jd_text, fields[] with UUIDs, evidence snippets, constraints | Pydantic + TypeScript |
| `fill_response.schema.json` | Server → Extension response: answers[] mapped to UUIDs, source attribution, confidence, needs_review flags | Pydantic + TypeScript |

## Key design properties

- `null` is a first-class value (distinguishes "unknown" from "zero" from "can guess")
- `_source` and `_confirmed_at` on attestation-sensitive fields
- `evidence_ids` on skills (a claim without backing evidence is unverified)
- `schema_version` for forward compatibility
