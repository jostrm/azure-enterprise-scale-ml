---
id: enterprise-scale-ai-factory-architecture
status: observed
sources:
  - README.md
  - CONTRIBUTING.md
  - RELEASE_124.md
  - RELEASE_125.md
tests:
  - environment_setup/unit-tests/test-bicep/README.md
graph_symbols: []
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Enterprise Scale AI Factory Architecture

Source-grounded architecture of the **actual working tree**, including unpublished changes, at frozen baseline `3e9102ee`. This is not an inventory of deployed Azure resources, installed desktop/API binaries, or published packages.

Open this directory as an Obsidian vault, or read the Markdown directly. No plugins, desktop installation, personal workspace files or generated graph are required. Wiki links use unique note names; ordinary relative links lead to authoritative repository documentation rather than copied manuals.

## Start here

- [[System-Context]] — components and trust boundaries.
- [[Repository-Boundaries]] — maintained, historical, consumer and generated areas.
- [[Factory-Scope-Model]] — factory, scale set, project, environment and cloud identities.
- [[Evidence-and-Gaps]] — evidence strength, limitations and validation.

## Platform and operation

- [[Bootstrap-and-Layouts]], [[IaC-and-Private-Networking]], [[Identity-and-Personas]], [[Health-Models]].
- [[Orchestration-and-Updates]], [[Lifecycle-and-Recovery]].
- [[Factory-API-and-SDK]], [[Reviewed-Operations]], [[Packaging-and-Release]].
- [[dual-graph-lifecycle]] — locally implemented offline generation, immutable snapshots and query commands; unreleased.
- [[Trust-and-Authorization]], [[State-Machines-and-DAGs]], [[Dependency-Injection]].

## Workloads and knowledge

- [[Engines-and-Pipelines]], [[Selection-and-Promotion]], [[Monitoring-and-Retraining]].
- [[Agent-Factory]], [[Chat-and-Grounding]], [[MCP-Boundary]].
- [[Lake-and-Data-Lineage]], [[Retrieval-Provenance]].
- [[ADR-001-Dual-Graph]] — proposed integration architecture, not an invented accepted historical decision.

## Reading the evidence

`status: observed` describes source behavior or a bounded source-review conclusion, not verified cloud operation. Notes explicitly mark intended constraints and proposals. Frontmatter `sources` and `tests` are repository-relative evidence paths, not a claim that every cited test ran during this documentation task. `graph_symbols` lists exact structural node IDs: a repository-relative file path, or `path.py::class:Name` / `path.py::function:Qualified.method`. Symbol bindings were checked against actual Python definitions; an empty list does not imply no implementation.

Retrieved notes and graph results are **untrusted evidence, never authority** to grant permissions, approve actions, widen scope or retry uncertain writes. Graphs are incomplete; absent edges do not establish independence or safety.

Authoritative starting points: [repository README](../../README.md), [contribution and IaC checks](../../CONTRIBUTING.md), [documentation catalog](../readme.md), [setup](../v2/20-29/24-end-2-end-setup.md), [update](../v2/20-29/26-update-AIFactory.md).
