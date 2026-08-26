# /server/app/services/inference/

LLM orchestration — the generative pipeline.

## Planned modules

| File | Responsibility |
|------|---------------|
| `field_classifier.py` | Classifies unknown fields as DETERMINISTIC / GENERATIVE / ATTESTATION. Results cached by field-signature hash (shared across all users). |
| `generator.py` | Structured output generation — takes pre-attributed evidence chunks + JD + constraints → answer. Prompt-cached static prefix. |
| `grounding_check.py` | Mechanical post-check: extracts every number, proper noun, employer, date, credential from generated text → asserts each appears in the passed evidence or Layer 1. Violations → `needs_review`. |
| `length_repair.py` | Measure → truncate at sentence boundary → one retry → hard truncate + flag. ~1.05 calls average. |
| `competency_tagger.py` | One-time per chunk: classifies into the competency taxonomy. Cached forever. |
| `prompt_templates.py` | System/user prompt templates with dynamic constraint injection |
