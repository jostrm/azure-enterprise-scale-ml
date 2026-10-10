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
reviewed_source: '21ea3380 + working tree; observed 2026-10-10'
---
# Retrieval provenance

## Two evidenced retrieval paths

**Agent Factory RAG:** explicit common/project source bindings pin approved text bytes and manifests. Operator reads and Search's own identity are separate. Managed-identity materialization copies exact approved files to isolated retrieval storage; evaluation data is excluded. Project-wide corpus approval is not automatic per-user document ACL enforcement or arbitrary PDF/image/audio ingestion.

**Factory Chat repository knowledge:** source scanning preserves source path/type, heading context, line ranges, content hash, revision/version/release metadata and working-tree provenance. Configured exclusions remove secrets, generated output, dependencies and unsupported material. Dated releases remain historical evidence.

`Knowledge` verifies owned index/container state and serializes refresh with a renewing lease. Changed refreshes stage a complete isolated owned Search index, wait boundedly for search visibility, verify all manifest fingerprints and scope metadata, then atomically promote the durable Blob manifest. Partial indexing failure does not mutate the serving generation or advance the committed manifest. Each answer pins retrieval and knowledge-status tools to one verified snapshot.

Text and voice can use the complete last-successful snapshot after blocked, failed, in-progress or stale refreshes. The answer and status disclose its committed timestamp, availability and freshness warning; fallback never means fresh or live evidence. Ownership/schema mismatch, missing or corrupt evidence and an unreconciled legacy in-place mutation still prevent serving. Generation creation needs separately approved index-definition write permission; refresh grants no roles, deletes no indexes and changes no service tier. Retained/failed generations require separately approved quota and retention maintenance. This is local source behavior, not proof of cloud rollout.

## Separation and limits

```text
source bytes -> selected chunks -> embeddings/index -> committed manifest -> cited answer
```

These transitions are not one transaction with source packaging or cloud application deployment. A local source edit is not present in an immutable cloud bundle until explicitly packaged/deployed; an index refresh cannot fetch that edit by assumption.

A content hash proves identity, not truth, permission or completeness. Citation paths/line ranges support review but can describe dirty source, old releases or excluded coverage. The locally implemented structural/architecture graph adds another provenance layer, not an alternative authorization mechanism; [[dual-graph-lifecycle]] distinguishes its immutable snapshot from Search ingestion.

See [[Chat-and-Grounding]], [[Agent-Factory]], [[Packaging-and-Release]], [[Lake-and-Data-Lineage]], [[Trust-and-Authorization]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [source-bound RAG](../../../usecase_code/40-agent-factory/45-rag-agent/readme.md), [repository ingestion and citations](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
