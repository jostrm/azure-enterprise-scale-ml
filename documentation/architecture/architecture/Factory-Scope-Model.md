---
id: factory-scope-model
status: observed
sources:
  - README.md
  - bootstrap/lib/factory_lifecycle.py
  - bootstrap/lib/aifactory_scaleset_config.py
  - bootstrap/lib/project_environment.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py
  - environment_setup/azurefactory-cli/src/azurefactory/review.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_factory_lifecycle.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_promotion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_security.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py::function:authorize
  - bootstrap/lib/factory_lifecycle.py::function:validate_manifest
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Factory scope model

## Observed

- **Factory:** registered logical identity with a stable UUID and human naming/configuration. A catalog entry may be only a draft.
- **Scale set:** explicit environment placement carrying tenant, subscription, region/network and provider bindings. Resolve its actual identity rather than interpreting “three subscriptions” in conceptual diagrams as a universal requirement.
- **Project:** stable logical project with one or more placements in selected scale sets. Adding a placement is configuration, not provisioning or model promotion.
- **Environment:** public lifecycle selection is `dev`, `stage`, `prod`; physical Azure resource naming and ML data contracts commonly use `test` for Stage. Never substitute the Azure ML environment asset named by runtime `environment` for `environment_name`.
- **Tenant and subscription:** separate validated identity and resource-container coordinates. Azure DevOps organization tenant may differ from the Azure resource tenant on supported routes.
- **Resource groups:** common/shared and project-specific resources enforce cost, access and operation boundaries. Shared hubs and DNS can introduce dependencies outside both groups.

Registered operations bind factory/scale-set/project IDs, exact environment, source revision, API target and published source. Agent `authorize` re-evaluates a grant for the **same scope and permission**, rather than combining permissions from another project.

## Constraints

Do not infer a target from the current CLI account, first discovered resource, department label or audience selector. Factory type extension points are not executable engines simply because a type appears in a catalog. `factory_lifecycle` rejects unsupported types.

Consumer layouts and naming versions matter; a familiar resource-group name is not ownership proof. Runtime manifests and immutable receipts are stronger than labels, but still require fresh live checks before execution.

See [[System-Context]], [[Reviewed-Operations]], [[Identity-and-Personas]], [[Lake-and-Data-Lineage]], [[Orchestration-and-Updates]] and [[Index]].

Authority: [CLI scope selection](../../../environment_setup/azurefactory-cli/readme.md), [project environment promotion](../../v2/20-29/26-update-AIFactory.md).
