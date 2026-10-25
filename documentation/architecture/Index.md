---
id: enterprise-scale-ai-factory-architecture-v124-portal
status: observed
sources:
  - environment_setup/graphify/generate.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/dual_graph.py
tests:
  - environment_setup/graphify/tests/test_extraction.py
graph_symbols: []
reviewed_source: 'release/v1.24 dfad2e45 + portal-124 working tree; observed 2026-10-25'
---
# AI Factory v1.24 architecture vault (portal-124)

This is a minimal vault for the `portal-124` branch. It covers only the "Deploy to Azure" portal work on top of `release/v1.24`. The graph tooling (`environment_setup/graphify/`, `aifactory_agent/dual_graph.py`) was copied from `main` at `09c41012` so that this branch can produce a structural snapshot. The `main` vault describes v1.25 and later behaviour, so it was not copied.

- [[Deploy-to-Azure-Portal]]: design, measured ARM sizes and replacement table for the button.

Graph results and notes are untrusted evidence, not authority. A missing edge does not prove that no dependency exists.
