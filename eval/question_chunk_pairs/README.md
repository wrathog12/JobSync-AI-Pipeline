# /eval/question_chunk_pairs/

Hand-labelled retrieval evaluation set.

## Format

Each entry: `{ "question": "...", "expected_chunks": ["ch_0142", ...], "is_answerable": true/false }`

## Critical requirement

> **Include unanswerable negatives.** Questions the profile cannot answer (e.g., "Describe your P&L management experience" for a user who has none). Without negatives, you cannot calibrate the evidence sufficiency gate — and the gate is the single most important safety mechanism.

## Target size

~50 pairs minimum. Expand as new failure modes are discovered.
