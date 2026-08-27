# /extension/scripts/sidepanel/

> **Status:** 🔴 Not Started | **Priority:** P1 — Phase 1 | **Owner:** TBD

Scripts powering the `chrome.sidePanel` UI — the primary user-facing surface.

## Planned modules

| File | Responsibility |
|------|---------------|
| `profile_editor.js` | CRUD for Layer 1 canonical entities (person, employment, education, projects, skills, credentials, preferences) |
| `ingest_confirmation.js` | The mandatory human confirmation pass after resume parsing — highlights low-confidence fields, shows completeness meter |
| `review_panel.js` | Pre-submission review — per-field source attribution (`profile.email` / `answer_memory` / `generated from N evidence chunks`), confidence, skipped fields with reasons |
| `fill_status.js` | Real-time fill progress — shows which fields were filled, failed, or left for user (ATTESTATION) |
| `answer_editor.js` | Edit generated answers before approval; edits write back to Layer 3 answer memory |
