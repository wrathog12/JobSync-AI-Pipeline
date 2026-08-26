# /server/tests/unit/

Unit tests — isolated module-level testing.

## Planned test modules

| File | Tests |
|------|-------|
| `test_field_classifier.py` | DETERMINISTIC / GENERATIVE / ATTESTATION classification accuracy |
| `test_attestation_deny_list.py` | **Non-negotiable**: every known attestation keyword triggers deny. Fail-closed on unknowns. |
| `test_grounding_check.py` | Numbers, proper nouns, employers, dates in output ⊆ evidence. Violations flagged. |
| `test_length_repair.py` | Measure/truncate/repair loop respects exact character limits |
| `test_chunker.py` | Natural-unit chunking preserves provenance, never splits bullets |
| `test_sanitizer.py` | LaTeX/HTML special character escaping |
