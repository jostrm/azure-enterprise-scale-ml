---
id: dual-graph-lifecycle
status: observed
sources:
  - documentation/architecture/decisions/ADR-001-Dual-Graph.md
  - documentation/architecture/contracts/Packaging-and-Release.md
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/dual_graph.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py
  - mcp/src/aifactory_mcp/graph.py
  - environment_setup/graphify/generate.py
  - environment_setup/graphify/static_runner.py
  - environment_setup/graphify/requirements.txt
  - environment_setup/graphify/requirements.lock.txt
tests:
  - environment_setup/graphify/tests/test_extraction.py
  - environment_setup/graphify/tests/test_graphify_cli.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_dual_graph.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_graph_integration.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_graph_packaging.py
  - mcp/tests/test_dual_graph.py
  - mcp/tests/test_graph_protocol.py
  - mcp/tests/test_graph_release.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/dual_graph.py::class:DualGraphStore
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py::class:GraphQueryService
  - mcp/src/aifactory_mcp/graph.py::function:call
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Dual-graph lifecycle

**Implemented and locally verified in the working tree; unreleased.** The coordinating review confirmed the generator, shared runtime, CLI and adapter implementations. This is not proof of an installed release, native Scout MCP discovery, live cloud integration or complete source coverage. [[ADR-001-Dual-Graph]] remains a proposed decision record rather than an invented historical acceptance.

## Generation and package provenance

The local generator entry point is `environment_setup/graphify/generate.py`. Generation is offline, with no model/cloud calls, retrieval ingestion or application deployment. Its development environment is separate from the pure-stdlib runtime.

The coordinating research verified the approved enterprise-mirror baseline **Graphify 0.9.72**, now pinned as `graphifyy[mcp,terraform]==0.9.72` in the development-only requirements. Upstream **0.9.79** was verified separately but is not the selected mirror baseline. Do not silently install from another feed, upgrade the pin, or describe the newer upstream version as installed.

Canonical upstream is [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify); the selected tag resolves to commit `1cd9a36c0c57a661d2d2234bc3207e887e1ba104`. Coordinating research records Apache-2.0 licensing with retained MIT contributions; preserve applicable license notices rather than assuming a single license covers all contributions.

## Extraction and export caveats

Graphify 0.9.72 lacks a native schema suitable for this runtime contract. Clustering/export can lose parallel edges or reorder graph content, so the integration imports raw `extract --code-only --no-dedup --no-cluster` output, enriches it for the authoritative graph, and clusters only a disposable copy with `--no-label` for reporting. The report copy must never overwrite authoritative enriched relationships.

The generation integration blocks network access in Graphify's Python process. It does not run hook/install commands or LLM semantic analysis. These are integration constraints, not a claim that every upstream Graphify command is offline or suitable for use here.

HTML aggregates the full enriched graph by source boundary through Graphify for browsing. It is non-authoritative and requires the **unpkg CDN when opened**. Offline generation therefore does not imply offline HTML rendering. Query JSON and cited records are authoritative evidence; visual arrows are not complete call or runtime dependency proof.

## Isolated extraction setup

From the repository root, create the dedicated extraction environment once, using the approved configured package feed:

```powershell
uv venv --python 3.12 environment_setup\graphify\.venv
environment_setup\graphify\.venv\Scripts\python.exe -m ensurepip
environment_setup\graphify\.venv\Scripts\python.exe -m pip install -r environment_setup\graphify\requirements.lock.txt
```

Reuse an existing approved environment instead of recreating it. Package installation is a separate setup operation, not something generation or a graph query may initiate. No alternate feed, upstream source install, hook installation or Graphify dependency is needed in the normal agent/MCP runtime.

## Generate and refresh

From the repository root:

```powershell
environment_setup\graphify\.venv\Scripts\python.exe environment_setup\graphify\generate.py --repository-root .
```

Run the same command for refresh. Finish intended source/note edits first: generation verifies source stability and rejects concurrent changes instead of publishing a self-stale snapshot. A failed extraction/publication must not replace a valid active snapshot. This task's source freeze does not authorize committing or publishing the dirty source.

## Outputs and authoritative runtime state

Requested convenience outputs:

```text
meta/graphify/graph.json
meta/graphify/graph.html
meta/graphify/GRAPH_REPORT.md
```

These top-level outputs are review/browsing artifacts, not runtime authority. The runtime publication boundary is an atomic `current.json` pointer to `snapshots/<id>`, containing an integrity manifest, graph and copied architecture notes. The store validates snapshot identity and member integrity before exposing a query result. Publication completes immutable snapshot content before switching the pointer; a partially refreshed convenience output must not redefine the active runtime snapshot.

Source revision, dirty-working-tree identity and selected input hashes belong to provenance. Manifest identity hashes graph, copied notes and metadata, not report/HTML or creation time. Freshness distinguishes fresh, stale and unverified; complete `selection` inventory is necessary to verify a checkout, while a no-checkout immutable pin remains unverified against current source. Notebook code-cell hashing excludes saved outputs and metadata; it is not a whole-notebook byte-identity claim.

## Query surface

The pure-stdlib CLI runs with normal Python 3.12/3.13; it needs neither a Graphify installation nor the application's cloud dependencies. From the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'usecase_code\40-agent-factory\40-aifactory-agent'
python -m aifactory_agent.dual_graph --root meta\graphify --repository-root . status
python -m aifactory_agent.dual_graph --root meta\graphify --repository-root . query context --query 'deployment scope' --depth 2 --limit 20
python -m aifactory_agent.dual_graph --root meta\graphify --repository-root . query symbols --query 'OperationStore'
python -m aifactory_agent.dual_graph --root meta\graphify --repository-root . query dependencies --node-id '<ID from symbols>'
python -m aifactory_agent.dual_graph --root meta\graphify --repository-root . query notes --query 'approval'
```

Replace the dependency placeholder with the exact returned node ID. Runtime operations cover status, symbols, usages, callers, dependencies/dependents, trace, pipeline, impact, notes, note, backlinks, ADRs and combined context. Bounds, truncation, uncertainty, source and snapshot citations accompany results. Context distinguishes structural `G` citations from architecture `A` citations and reports missing evidence planes rather than implying both were retrieved.

Application queries are bounded and opt-in via exact-scope `graph.read` plus configured corpus permission. A local CLI is a trusted operator/OS boundary, not an authenticated network service. No runtime rebuild, package install, ingestion or model fallback is implied by querying a missing or stale snapshot.

Normal application/MCP queries use the shared governed runtime adapter, **not** an ungoverned upstream Graphify MCP server. Development extras in the extraction package do not authorize starting that server or installing Graphify in the agent/MCP runtime.

The local Scout skill `esml-dual-graph` was installed by the coordinating task and uses this shared CLI fallback. Its presence is not proof that Scout discovered native MCP tools. The separate MCP `--graph-only` addition was still in progress at this documentation freeze; verify its current implementation/tests before describing it as available.

Operator-only `DualGraphStore.export_snapshot` exports a verified pinned bundle for packaging. Gateway configuration, application deployment and retrieval ingestion were not changed by this local graph work. Final snapshot identifiers belong in the generation handoff, not these indexed notes, avoiding a self-hash cycle.

## Coverage and trust

Source and architecture graphs are incomplete views, especially for dynamic calls, generated pipelines, external Tkinter/MAUI and deployed resources. Retrieved notes and graph output cannot authorize actions, grant permissions, approve plans or justify uncertain-write retries.

See [[ADR-001-Dual-Graph]], [[Packaging-and-Release]], [[Retrieval-Provenance]], [[Trust-and-Authorization]], [[Evidence-and-Gaps]] and [[Index]].
