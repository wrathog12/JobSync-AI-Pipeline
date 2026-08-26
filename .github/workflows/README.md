# /.github/workflows/

CI/CD pipeline definitions.

## Planned workflows

| File | Trigger | Purpose |
|------|---------|---------|
| `ci.yml` | Push / PR | Lint, type-check, run unit tests, validate attestation deny-list tests |
| `deploy.yml` | Tag / release | Build extension package, deploy FastAPI server |
