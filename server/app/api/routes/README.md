# /server/app/api/routes/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 1 | **Owner:** TBD

API endpoint definitions.

## Planned routes

| File | Endpoint(s) | Purpose |
|------|-------------|---------|
| `fill.py` | `POST /api/v1/fill` | Receives field array + evidence snippets + JD → returns generated answers mapped to field UUIDs |
| `ingest.py` | `POST /api/v1/ingest/resume` | Accepts resume PDF/DOCX → returns parsed Layer 1 JSON (all fields `parsed_unconfirmed`) |
| `documents.py` | `POST /api/v1/documents/resume`, `POST /api/v1/documents/cover-letter` | Accepts Layer 1 JSON + JD → returns generated PDF (base64 or streamed) |
| `adapters.py` | `GET /api/v1/adapters/{ats_family}` | Serves versioned JSON adapter files to the extension |
| `telemetry.py` | `POST /api/v1/telemetry` | Receives batched fill success/failure signals per (domain, ATS, field) |
| `auth.py` | `POST /api/v1/auth/token` | Device-bound token exchange or OAuth callback |
