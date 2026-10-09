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
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_project_deployment_contract.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_only_launchers.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_promotion.py
  - environment_setup/unit-tests/test-bicep/unit/test_ci_runner.py
graph_symbols:
  - bootstrap/lib/project_deployment.py::class:Deployment
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Orchestration and updates

## Observed

ADO/GHA templates orchestrate common and selected project infrastructure. Project dispatch carries reviewed environment, project identity, configuration hash and correlation ID; `project_deployment.py` validates provider repository and run correlation rather than treating any successful workflow as this deployment.

Legacy update distinguishes library/template refresh from feature update and project-only execution. Normal helper workflows can update templates/configuration, commit, push, dispatch and monitor. They are not read-only inspection commands.

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

See [[Bootstrap-and-Layouts]], [[Lifecycle-and-Recovery]], [[Factory-Scope-Model]], [[Engines-and-Pipelines]], [[State-Machines-and-DAGs]] and [[Index]].

Authority: [update behavior and version compatibility](../../v2/20-29/26-update-AIFactory.md), [GHA topology and runners](../../gh-io/docs/orchestrators/gh.md), [current MLOps templates](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md).
