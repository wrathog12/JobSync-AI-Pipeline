# /extension/schemas/

TypeScript type definitions generated from the shared source-of-truth schemas.

> These are **generated** from `/shared/schemas/`, not hand-maintained.
> The canonical source is the shared Pydantic/JSON Schema definitions.

## Planned files

| File | Contents |
|------|----------|
| `profile.d.ts` | Layer 1 canonical entity types (Person, Employment, Education, Project, Skill, Credential, Preference, Authorization) |
| `payload.d.ts` | Outbound payload structure (page_url, job_description_raw, fields[]) |
| `evidence.d.ts` | Layer 2 evidence chunk record with provenance fields |
| `answer_memory.d.ts` | Layer 3 approved answer record |
