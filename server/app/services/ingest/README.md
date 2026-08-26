# /server/app/services/ingest/

Resume/profile ingestion pipeline.

## Flow

```
Upload (PDF / DOCX / LinkedIn export / paste)
   ↓  text extraction, layout-aware
   ↓  LLM → structured extraction against the Layer 1 JSON schema
   ↓  every field tagged confidence: parsed_unconfirmed
   ↓
► MANDATORY HUMAN CONFIRMATION PASS ◄  (extension side)
   ↓
Layer 1 committed → Layer 2 derived (chunk, tag, index)
```

## Planned modules

| File | Responsibility |
|------|---------------|
| `parser.py` | PDF/DOCX text extraction — handles multi-column layouts, tables, headers/footers |
| `extractor.py` | LLM-powered structured extraction → Layer 1 JSON schema. All fields `parsed_unconfirmed`. |
| `chunker.py` | Derives Layer 2 evidence chunks from confirmed Layer 1 entities. Natural-unit chunking (1 bullet = 1 chunk), never fixed-size sliding windows. |
| `hasher.py` | Content-hash per chunk for incremental re-ingest — only re-embed changed chunks on profile edit |
