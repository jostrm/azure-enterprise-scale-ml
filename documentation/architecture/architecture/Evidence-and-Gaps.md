---
id: evidence-and-gaps
status: observed
sources:
  - CONTRIBUTING.md
  - RELEASE_125.md
  - ROADMAP_MAIN.md
  - documentation/v2/20-29/25-personas-aifactory.md
  - environment_setup/aifactory/bicep/esml-genai-1/1-10-SUMMARY.md
  - usecase_code/30-machine-learning/README.md
tests:
  - environment_setup/unit-tests/test-bicep/README.md
  - esml-v2/tests/test_esml_packaging.py
graph_symbols: []
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Evidence and gaps

## Evidence hierarchy used here

1. Actual entry point, implementation and contract in the working tree.
2. Relevant tests indicating intended observable behavior and negative cases.
3. Maintained operational documentation that matches those paths.
4. Release notes and older diagrams as dated context, not installation proof.

`RELEASE_125.md` identifies a historical release-branch snapshot and also contains later clarification. Neither the note nor a changed README establishes that an installed API, wheel, container image or Azure resource includes current dirty source. The persona guide explicitly distinguishes baseline group support from the unreleased `groups-v1` policy.

## Bounded findings

- External Tkinter/MAUI implementation was not inspected outside this checkout. SDK/CLI contracts and packaging documentation establish the integration boundary, not a live API capability.
- No Azure, provider, model, package-index or deployment call was made for this vault. No claims of current tenant health, permissions or deployed versions are inferred from existing test/demo reports.
- Historical phase summaries can drift: `1-10-SUMMARY.md` names some phase files differently from the actual `esml-genai-1` tree. Use current pipeline and Bicep entry points, not its timing or “mission accomplished” claims.
- `30-machine-learning/README.md` provides no substantive ML architecture evidence. Current ML contracts live in model-factory and ESML v2.
- No automatic drift-triggered retraining or managed online feature-store service was established by the reviewed current ML engines. Do not infer either from historical “featurestore” language.
- Static graphs cannot fully resolve dynamic dispatch, external APIs, generated provider templates or runtime/cloud dependencies. Missing edges are not negative proof.

## Validation boundary

Vault validation checks note frontmatter, unique IDs, wiki-link resolution, source/test existence, relative Markdown destinations and inbound navigation. It does not validate every historical link in the entire repository or external network URLs. Referenced implementation tests were inspected as evidence, not rerun for prose-only changes.

See [[Repository-Boundaries]], [[Packaging-and-Release]], [[Monitoring-and-Retraining]], [[ADR-001-Dual-Graph]], [[Trust-and-Authorization]] and [[Index]].

Authority: [contribution checks](../../../CONTRIBUTING.md), [release caveats](../../../RELEASE_125.md), [persona evidence](../../v2/20-29/25-personas-aifactory.md).
