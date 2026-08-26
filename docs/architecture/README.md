# /docs/architecture/

System architecture documentation.

## Planned documents

| File | Contents |
|------|----------|
| `system_overview.md` | High-level architecture: extension ↔ backend decoupling, data flow, privacy boundary |
| `knowledge_layers.md` | The 3-layer knowledge model: Layer 1 (canonical profile), Layer 2 (provenanced evidence), Layer 3 (answer memory) |
| `retrieval_algorithm.md` | The full retrieval pipeline: Layer 3 → Layer 2 candidate generation → rerank → evidence sufficiency gate → generate → ground-check |
| `field_classification.md` | DETERMINISTIC / GENERATIVE / ATTESTATION routing logic and deny-list |
