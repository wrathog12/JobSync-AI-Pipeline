# /server/app/schemas/

Pydantic request/response schemas — **generated from `/shared/schemas/`**.

> Do NOT hand-maintain these. They are derived from the single source of truth in `/shared/`.

## Planned files

| File | Contents |
|------|----------|
| `profile.py` | Layer 1 canonical entity models (Person, Employment, Education, Project, Skill, Credential, Preference, Authorization) |
| `fill_request.py` | Inbound payload: fields[] with UUIDs, evidence snippets, JD, constraints |
| `fill_response.py` | Outbound: answers[] mapped back to field UUIDs, with source attribution and confidence |
| `evidence.py` | Layer 2 evidence chunk with provenance (entity_id, employer_id, date_range, competency_tags) |
| `ingest.py` | Resume parse request/response schemas |
