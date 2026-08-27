# /extension/scripts/background/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 1 Critical Path | **Owner:** TBD

Service worker (MV3 background script).

## Planned modules

| File | Responsibility |
|------|---------------|
| `service_worker.js` | Entry point — registers listeners, manages lifecycle |
| `api_client.js` | Authenticated fetch wrapper to the FastAPI backend |
| `session_manager.js` | Application-scoped state machine in `chrome.storage.local` — tracks multi-page wizard progress (tenant + requisition_id), fields filled/failed, user edits, used chunks |
| `auth.js` | `chrome.identity` OAuth flow or device-bound token management |
| `telemetry.js` | Collects per-fill success/failure signals from the verifier, batches and sends to backend |
