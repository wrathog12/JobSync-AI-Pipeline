# /shared/taxonomies/

Fixed classification systems used by both client and server.

## Planned files

| File | Contents |
|------|----------|
| `competencies.json` | ~15-25 competency tags: `leadership`, `conflict_resolution`, `ambiguity`, `technical_depth`, `failure_and_learning`, `influence_without_authority`, `mentorship`, `ownership`, `customer_focus`, `scale`, `process_improvement`, etc. Used for query construction (§3.5) and evidence retrieval filtering. |
| `field_categories.json` | Three-way classification enum: `DETERMINISTIC` (Layer 1 key lookup), `GENERATIVE` (Layers 2-3 → LLM), `ATTESTATION` (never auto-filled) |
| `canonical_questions.json` | Alias dictionary — maps the many phrasings of common questions to canonical IDs. Drives Layer 3 answer memory hits and field classification caching. |
