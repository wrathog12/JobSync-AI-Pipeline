# /server/tests/integration/

Integration tests — end-to-end API round trips.

## Planned test modules

| File | Tests |
|------|-------|
| `test_fill_pipeline.py` | Full request: fields[] + evidence + JD → response with answers, sources, confidence |
| `test_ingest_pipeline.py` | Resume upload → parsed Layer 1 JSON → all fields `parsed_unconfirmed` |
| `test_document_generation.py` | Layer 1 JSON + JD → PDF output validates through ATS parser |
| `test_auth_flow.py` | Token exchange, rate limiting, cost breaker triggers |
