# /shared/

Single source of truth for cross-cutting definitions shared between the extension (TypeScript) and server (Python).

> Generate language-specific types from these definitions. Never hand-maintain two copies.

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `schemas/` | Canonical entity JSON schemas (Layer 1 profile, evidence chunks, payloads) |
| `taxonomies/` | Competency taxonomy, field classification categories, canonical question IDs |
| `deny_lists/` | ATTESTATION deny-list — keywords and canonical question IDs that must never be auto-filled |
