---
id: adr-001-dual-graph
status: proposed
sources:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/ports.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/knowledge.py
  - mcp/src/aifactory_mcp/runtime.py
  - documentation/architecture/Index.md
tests:
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_services.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_conversation.py
  - mcp/tests/test_runtime.py
graph_symbols: []
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# ADR-001: source and architecture dual graph

**Status: proposed.** This records the requested architecture, not an accepted historic decision or proof of installed/deployed capability. The coordinating review has now confirmed local working-tree implementation; observed interfaces, commands and limitations live in [[dual-graph-lifecycle]]. Implementation does not retroactively make this ADR accepted.

## Context

Text retrieval explains source passages but does not alone expose structural code relationships or curated cross-cutting architecture. Conversely, a structural graph cannot explain every external/cloud contract, dynamic call or operational constraint. Both views need provenance and honest coverage limits.

## Proposed decision and boundaries

1. Share a pure-standard-library runtime in `aifactory_agent.dual_graph`; do not duplicate graph parsing/query behavior in Chat and MCP.
2. Keep source generation under `environment_setup/graphify`, with generated artifacts under `meta/graphify`. Generation is offline: **no model or cloud calls**, no ingestion, no deployment.
3. Produce immutable snapshots that bind selected source bytes and architecture notes to their provenance. Preserve dirty-source identity instead of claiming the baseline commit contains unpublished changes.
4. Maintain separate structural and architecture relationships. Architecture links may be cyclic; a static code edge is not a complete runtime dependency proof.
5. Make retrieval opt-in through exact-scope `graph.read` **and** configured corpus scope permission. Tool discovery and dispatch must enforce the same authorization.
6. Use bounded queries and immutable snapshot identity; report stale, missing, degraded and incomplete coverage. Do not silently substitute another corpus or treat no results as proof of no dependency.
7. Expose architecture notes and backlinks without requiring Obsidian, plugins or personal workspace files. Frontmatter source/test paths remain reviewable independently of the generator.

## Security and alternatives

Retrieved notes and graph output can never approve actions, change grants, widen scope, supply a confirmation phrase or authorize uncertain-write retries. Ordinary source/architecture data is not policy. Exclude credentials, private configuration, customer runtime data, logs and generated dependency trees.

Rejected architectural direction: separate ad hoc parsers in each client, cloud/model-dependent graph generation, or treating the graph as a complete execution/deletion plan.

## Decision acceptance and operational evidence

Local implementation and focused tests now cover exported runtime symbols, snapshot validation, path/scope confinement, generation, backlink/context behavior and adapter contracts; the lifecycle note links their actual paths. Formal decision acceptance, publication, installed-package availability and cloud integration remain unverified. Packaging a graph must not trigger cloud source deployment or retrieval ingestion. The tests above establish the surrounding composition boundaries, not ADR acceptance.

[[dual-graph-lifecycle]] records the verified CLI/generator commands, approved-mirror dependency baseline, extraction caveats, convenience outputs and implemented authoritative snapshot publication boundary.

See [[Chat-and-Grounding]], [[MCP-Boundary]], [[Retrieval-Provenance]], [[Packaging-and-Release]], [[State-Machines-and-DAGs]], [[Dependency-Injection]], [[Trust-and-Authorization]], [[Evidence-and-Gaps]] and [[Index]].
