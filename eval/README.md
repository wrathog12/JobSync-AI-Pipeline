# /eval/

Retrieval evaluation and safety test datasets.

## Purpose

Phase 0 deliverable — without these, you cannot calibrate the evidence sufficiency gate (§3.6 step 4) or validate the attestation deny-list.

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `question_chunk_pairs/` | ~50 hand-labelled (question → correct evidence chunk) pairs, **including unanswerable negatives**. The negatives are what calibrate the abstention floor. |
| `attestation_tests/` | Test cases asserting every known attestation keyword/question is correctly denied. Fail-closed validation. |
