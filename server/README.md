# /server/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 0-1 | **Owner:** TBD

FastAPI backend — the Inference and Processing Layer.

## Structure

```
server/
├── app/
│   ├── api/
│   │   ├── routes/        # Endpoint definitions
│   │   └── middleware/     # Auth, rate limiting, cost circuit breaker
│   ├── core/              # Config, settings, constants
│   ├── services/
│   │   ├── inference/     # LLM orchestration, field classification, grounding check
│   │   ├── documents/     # Resume/cover letter PDF generation (HTML → Chromium → PDF)
│   │   └── ingest/        # Resume parsing, Layer 1 extraction, chunk derivation
│   ├── models/            # Pydantic ORM / DB models
│   └── schemas/           # Pydantic request/response schemas (generated from /shared/)
├── templates/
│   ├── resume/            # HTML resume templates (Jinja2 with rebound delimiters)
│   └── cover_letter/      # HTML cover letter templates
└── tests/
    ├── fixtures/
    │   ├── html/          # Saved real ATS form HTML for golden-fixture testing
    │   └── profiles/      # Sample Layer 1 profile JSON for test scenarios
    ├── unit/              # Unit tests
    └── integration/       # End-to-end API tests
```
