# /server/app/api/middleware/

> **Status:** 🔴 Not Started | **Priority:** P1 — Phase 1 | **Owner:** TBD

Request middleware pipeline.

## Planned modules

| File | Responsibility |
|------|---------------|
| `auth_middleware.py` | Validates device-bound tokens or OAuth bearer tokens |
| `rate_limiter.py` | Per-user rate limits (requests/minute, tokens/day) |
| `cost_breaker.py` | Hard per-request token ceiling + global cost circuit breaker — prevents runaway LLM spend |
| `cors.py` | CORS configuration for extension origin |
