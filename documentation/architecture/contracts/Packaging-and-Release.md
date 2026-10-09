---
id: packaging-and-release
status: observed
sources:
  - RELEASE_125.md
  - environment_setup/install_config_wizard/readme.md
  - environment_setup/azurefactory-cli/setup.py
  - esml-v2/esml_build.py
  - usecase_code/40-agent-factory/40-aifactory-agent/deploy.py
  - usecase_code/40-agent-factory/40-aifactory-agent/readme.md
tests:
  - environment_setup/azurefactory-cli/tests/test_enrollment_packaging.py
  - esml-v2/tests/test_esml_packaging.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_skill_packaging.py
graph_symbols:
  - esml-v2/esml_build.py::function:_source
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Packaging and release

## Observed freezes

| Artifact | What it freezes; what it does not prove |
|---|---|
| Published source commit | Approved source identity for execution; not installed package or deployment state. |
| Consumer template copy | The copied revision plus consumer edits; not an automatically updating mirror. |
| CLI wheel/sdist | SDK/CLI and vendored canonical enrollment support; not the external running Factory API. |
| ESML v2 wheel/sdist | `azure_esml` plus canonical shared model-factory engines and policy; not a published package-index release or trained model. |
| Agent application source bundle | Approved deployable application/repository snapshot; not a refresh of an already running cloud image. |
| Ingestion manifest/index | Successfully reconciled source chunk hashes and provenance; not a new source checkout or permission grant. |
| Graph snapshot | Locally implemented immutable source/architecture evidence for offline queries; not full runtime/cloud discovery or publication proof. |

The agent's cloud source snapshot is immutable. Refreshing retrieval against it does not fetch new local edits; first package/deploy an approved updated snapshot, then separately authorize ingestion. Ingestion may embed documents and mutate owned retrieval resources; inference is another operation.

The SDK, Agent Factory operator and grounded application have different dependency/runtime requirements. Do not share environments based on similar directory names. Installed packages should be tested through their declared public surfaces, not accidental source-path imports.

Release notes explicitly distinguish branch snapshots from GA/publication. The current dirty working tree includes changes after those snapshots. A release label, successful build or local source test cannot establish installed API support or live compatibility.

## Intended separation

Graph runtime queries are standard-library-only. Generation remains offline and outside model/cloud deployment and ingestion. [[dual-graph-lifecycle]] records the locally verified paths and interfaces; [[ADR-001-Dual-Graph]] remains proposed as a decision record.

[[dual-graph-lifecycle]] distinguishes requested top-level review outputs from the immutable manifest-validated runtime snapshot, records the verified approved-mirror Graphify 0.9.72 development pin, and explains extraction/export limitations.

See [[Repository-Boundaries]], [[Factory-API-and-SDK]], [[Chat-and-Grounding]], [[Retrieval-Provenance]], [[Evidence-and-Gaps]] and [[Index]].

Authority: [release caveats](../../../RELEASE_125.md), [SDK packaging](../../../environment_setup/azurefactory-cli/readme.md), [ML package boundary](../../v2/30-39/37-mlops.md), [agent deployment](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
