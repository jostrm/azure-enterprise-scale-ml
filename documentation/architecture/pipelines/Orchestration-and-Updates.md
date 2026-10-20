---
id: orchestration-and-updates
status: observed
sources:
  - bootstrap/GH-update-aifactory-and-run-project.sh
  - bootstrap/ADO-update-aifactory-and-run-project.sh
  - bootstrap/lib/project_deployment.py
  - bootstrap/lib/project_environment.py
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml
  - documentation/v2/20-29/26-update-AIFactory.md
  - .github/workflows/infrastructure-tests.yml
  - environment_setup/unit-tests/test-bicep/azure-pipelines.yml
  - environment_setup/unit-tests/test-bicep/run_ci.py
  - environment_setup/unit-tests/test-bicep/tiers.py
  - environment_setup/unit-tests/test-bicep/base/tiers.py
  - environment_setup/unit-tests/test-bicep/conftest.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_project_deployment_contract.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_only_launchers.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_promotion.py
  - environment_setup/unit-tests/test-bicep/unit/test_ci_runner.py
  - environment_setup/unit-tests/test-bicep/unit/test_tiers.py
graph_symbols:
  - bootstrap/lib/project_deployment.py::class:Deployment
reviewed_source: '3e9102ee + working tree; observed 2026-10-07; Credential-free CI re-observed at f08ed1ef + working tree 2026-10-20'
---
# Orchestration and updates

## Observed

ADO/GHA templates orchestrate common and selected project infrastructure. Project dispatch carries reviewed environment, project identity, configuration hash and correlation ID; `project_deployment.py` validates provider repository and run correlation rather than treating any successful workflow as this deployment.

Legacy update distinguishes library/template refresh from feature update and project-only execution. Normal helper workflows can update templates/configuration, commit, push, dispatch and monitor. They are not read-only inspection commands.

Ordinary version-aware ADO/GHA updates use `aif_version_checkout` to attach the
selected source branch and configure its origin upstream. Local branches may
only fast-forward to the already resolved exact SHA; dirty/ahead/diverged work
or a remote tip changed since selection blocks rather than resets or changes
the selected revision. The exact SHA remains in the parent gitlink and version
record. `aif_version_prepare` captures caller pin/review intent before exporting
the resolved SHA; explicit pins/reviewed versions stay detached. Creation,
project-only and governed deployment routes are not switched to floating refs.
The older v1.24 GH launcher already attaches its release branch and is unchanged.

The legacy ADO updater prompts before authentication for an optional project-URL
override, even when organization/project defaults were previously saved. Official
HTTPS `dev.azure.com` and `*.visualstudio.com` URLs are split into organization and
project, validated, displayed and persisted through the existing local settings
writer. Noninteractive destination lookup and reviewed/registered routing remain
unchanged. The override selects a destination; it does not grant tenant access or
authorize a deployment.

The legacy project ADO Run UI uses `deploymentTarget: manual` and
`not-applicable` project/hash defaults because empty string parameters are treated
as required by that UI. A compile-time `reviewedDeploymentTarget` maps manual to
the existing empty-target promotion flow; explicitly empty API targets remain
compatible. The JSON override selects configuration input independently of this
mode. Explicit reviewed Dev/Stage/Prod targets still invoke protected per-run
configuration validation even with the override unchecked. Manual Dev-only runs
must explicitly deselect Stage and Prod in the Run UI.

GitHub manual project dispatch accepts empty optional reviewed fields and an empty
configuration path without ADO sentinels. Any reviewed metadata or reserved path
activates protected-secret/hash/exact-target checks before phase overrides/login.
JSON-first identity selection is independent and cannot replace that contract.
The reusable phase workflow's configuration path is optional, matching the
variables/secrets-only dispatch route. GitHub subnet allocation uses the
authenticated Azure CLI context rather than an Az PowerShell session.

Explicit Stage/Prod selection uses the reviewed single-project route. Stage requires a real Dev project resource group; Prod requires real Dev **or** Stage. The checks validate exact subscription/tenant, resource identity and applicable location/provisioning state. Failed reads block rather than being interpreted as absence. A saved review, common resource group or pipeline receipt is not predecessor-deployment proof.

Registered roots instead use protected scoped lifecycle manifests; ordinary legacy flags cannot replace exact reviewed factory, scale set, project, environment, version and commit. Source version selection does not migrate directories.

## Dependency and identity boundaries

GHA OIDC identity routing and ADO service-connection selection are distinct provider mechanisms. Authentication, provider authorization, private runner connectivity, source publication and deployment approval must all succeed. A local configuration save grants none of these.

DataOps/MLOps templates in `copy_my_subfolders_to_my_grandparent` orchestrate workload jobs, not whole-factory state transitions. Generated workflow/job artifacts are execution inputs; canonical template source and consumer configuration remain separate.

## Credential-free CI

The shared runner keeps `LIVE_AZURE=0` and excludes live integration tests.
Windows unit subprocesses have a 40-minute budget, with a 50-minute outer job
budget in both GitHub Actions and Azure Pipelines for setup and report upload.
Linux unit subprocesses retain 20 minutes and Linux jobs retain 30 minutes.
Persona preflight readiness is runtime state, not a public `.env` input.

Unit tests are split into tiers 1-5 (core, pipelines, infra, lifecycle, capacity).
`tiers.py` assigns every offline test file to exactly one tier, and
`unit/test_tiers.py` rejects an unassigned or stale file. The selection comes from
`--tiers`, then `AIF_TEST_TIERS`, then the `tiers.py` default `1-4`, so push and pull
request runs skip tier 5 (preflight and capacity). `run_ci.py` validates the
selection for the unit phase only, passes it to pytest and records it in
`unit-summary.json`. The GitHub workflows take a `tiers` dispatch input or the
`AIF_TEST_TIERS` repository variable; Azure Pipelines takes only a `testTiers`
parameter. GitHub runs every tier nightly; Azure Pipelines does so on nights when
`main` changed (`always: false`). Each event type has its own GitHub concurrency
group, so a push cannot cancel the nightly run.

See [[Bootstrap-and-Layouts]], [[Lifecycle-and-Recovery]], [[Factory-Scope-Model]], [[Engines-and-Pipelines]], [[State-Machines-and-DAGs]] and [[Index]].

Authority: [update behavior and version compatibility](../../v2/20-29/26-update-AIFactory.md), [GHA topology and runners](../../gh-io/docs/orchestrators/gh.md), [current MLOps templates](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md).
