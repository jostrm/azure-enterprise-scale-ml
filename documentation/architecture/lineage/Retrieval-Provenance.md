---
id: retrieval-provenance
status: observed
sources:
  - usecase_code/40-agent-factory/agent_factory/rag_sources.py
  - usecase_code/40-agent-factory/agent_factory/rag_materialization.py
  - usecase_code/40-agent-factory/agent_factory/rag_indexing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/knowledge.py
  - usecase_code/40-agent-factory/40-aifactory-agent/readme.md
tests:
  - usecase_code/40-agent-factory/tests/test_rag_sources.py
  - usecase_code/40-agent-factory/tests/test_rag_materialization.py
  - usecase_code/40-agent-factory/tests/test_rag_indexing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_knowledge.py
graph_symbols:
  - usecase_code/40-agent-factory/agent_factory/rag_sources.py::function:parse_source
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/knowledge.py::function:scan_sources
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/knowledge.py::function:Knowledge.refresh
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Retrieval provenance

## Two evidenced retrieval paths

**Agent Factory RAG:** explicit common/project source bindings pin approved text bytes and manifests. Operator reads and Search's own identity are separate. Managed-identity materialization copies exact approved files to isolated retrieval storage; evaluation data is excluded. Project-wide corpus approval is not automatic per-user document ACL enforcement or arbitrary PDF/image/audio ingestion.

**Factory Chat repository knowledge:** source scanning preserves source path/type, heading context, line ranges, content hash, revision/version/release metadata and working-tree provenance. Configured exclusions remove secrets, generated output, dependencies and unsupported material. Dated releases remain historical evidence.

`Knowledge` verifies owned index/container state, serializes refresh with a renewing lease and reconciles changed/removed task-owned documents against a durable Blob manifest. Partial indexing failure does not advance the committed manifest. Status distinguishes unavailable, stale and reconciled state; Chat refuses unready evidence.

## Separation and limits

```text
source bytes -> selected chunks -> embeddings/index -> committed manifest -> cited answer
```

These transitions are not one transaction with source packaging or cloud application deployment. A local source edit is not present in an immutable cloud bundle until explicitly packaged/deployed; an index refresh cannot fetch that edit by assumption.

A content hash proves identity, not truth, permission or completeness. Citation paths/line ranges support review but can describe dirty source, old releases or excluded coverage. The locally implemented structural/architecture graph adds another provenance layer, not an alternative authorization mechanism; [[dual-graph-lifecycle]] distinguishes its immutable snapshot from Search ingestion.

See [[Chat-and-Grounding]], [[Agent-Factory]], [[Packaging-and-Release]], [[Lake-and-Data-Lineage]], [[Trust-and-Authorization]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [source-bound RAG](../../../usecase_code/40-agent-factory/45-rag-agent/readme.md), [repository ingestion and citations](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
