# /extension/scripts/utils/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 1 Foundation | **Owner:** TBD

Shared utility modules used across content scripts, background, and side panel.

## Planned modules

| File | Responsibility |
|------|---------------|
| `bm25.js` | Lexical retrieval engine — BM25 over the user's Layer 2 evidence chunks (≤2k chunks, runs in 1-3ms) |
| `evidence_index.js` | Layer 2 local index — manages chunked evidence records in IndexedDB, content-hash invalidation on profile edits |
| `answer_memory.js` | Layer 3 — stores/retrieves past human-approved answers keyed by canonical_question_id + company |
| `field_classifier.js` | Client-side first pass: classifies fields as DETERMINISTIC / GENERATIVE / ATTESTATION using the adapter map + alias dictionary |
| `layer1_store.js` | Layer 1 canonical profile — typed entity CRUD over `chrome.storage.local` / IndexedDB |
| `crypto_utils.js` | UUID generation, content hashing for chunk deduplication |
