# /server/app/services/documents/

> **Status:** ⚪ Deferred | **Priority:** P2 — Phase 3 | **Owner:** TBD

Document generation service — resume and cover letter PDF creation.

## Architecture

Uses **HTML template → Chromium → PDF** (not LaTeX).

1. Jinja2 templates with rebound delimiters (`<% %>` or `[[ ]]`) to avoid collision with any template syntax
2. Layer 1 JSON data injected into validated HTML templates
3. Chromium headless renders to PDF (via Playwright or Puppeteer)
4. `.docx` generated alongside for ATS compatibility
5. Result streamed or base64-encoded back to extension

## Planned modules

| File | Responsibility |
|------|---------------|
| `renderer.py` | Template loading, data injection, Chromium PDF subprocess |
| `sanitizer.py` | Escapes special characters in AI-generated content before template injection |
| `tailorer.py` | Reorders and reweights existing Layer 1 facts against a JD — never invents new facts |
