# /shared/deny_lists/

> **Status:** 🔴 Not Started | **Priority:** P0 — Phase 0 Non-Negotiable | **Owner:** TBD

ATTESTATION deny-list — versioned, tested data that prevents auto-filling legally sensitive fields.

## Purpose (§5.1)

Fields where a wrong answer is **fraud**, not a quality problem:
- Work authorization / visa / sponsorship
- Criminal history, background-check consent
- Education verification (degree, institution, dates, GPA)
- Employment dates and titles (background-check verified)
- Professional licences, security clearances
- EEO/OFCCP demographics (race, gender, veteran, disability)
- Salary history (illegal to ask in several US jurisdictions)
- "I certify the above is true" checkboxes

## Planned files

| File | Contents |
|------|----------|
| `attestation_keywords.json` | Keyword net: `sponsor`, `authoriz`, `visa`, `felony`, `convict`, `veteran`, `disab`, `race`, `ethnic`, `gender`, `certif`, `clearance`, `GPA`, `salary histor`, `background check`, etc. |
| `attestation_question_ids.json` | Canonical question IDs that are always ATTESTATION regardless of phrasing |

## Critical rule

> **Fail closed.** An unclassifiable field defaults to ATTESTATION, never GENERATIVE.
