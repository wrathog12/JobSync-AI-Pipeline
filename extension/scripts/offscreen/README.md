# /extension/scripts/offscreen/

> **Status:** ⚪ Deferred | **Priority:** P3 — Phase 3 Only | **Owner:** TBD

Offscreen document scripts (Phase 3).

Used for compute-heavy tasks that would block or be killed in the service worker:
- Dense embedding inference via `transformers.js` (quantized MiniLM, ~20-25 MB WASM)
- Flat exact cosine similarity search over `Float32Array` vectors stored in IndexedDB
- Runs in a hidden DOM context with full Web API access

> Not needed until Phase 3. BM25 + structured filters handle Phases 1–2.
