# /server/tests/fixtures/profiles/

Sample Layer 1 profile JSON files for testing.

## Purpose

- Test inference with known inputs → deterministic expected outputs
- Test attestation deny-list (profiles with/without authorization data)
- Test edge cases: incomplete profiles, null fields, unverified skills
- Test grounding check with known evidence sets

## Planned fixtures

| File | Scenario |
|------|----------|
| `complete_profile.json` | Fully populated Layer 1 profile |
| `incomplete_profile.json` | Gaps in education, missing GPA, partial skills |
| `no_authorization.json` | Authorization fields null — tests ATTESTATION gating |
| `multi_employer.json` | 4+ employers — tests cross-attribution prevention |
