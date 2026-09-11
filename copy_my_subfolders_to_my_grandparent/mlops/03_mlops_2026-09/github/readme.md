# GitHub Actions installation

This workflow is inactive in this template folder. An administrator must manually
copy `ml-factory.yml` into `.github\workflows\ml-factory.yml` of the consuming repository.
It exposes **workflow_call** and **workflow_dispatch** only; it has no push/PR trigger.
Provision Python/factory dependencies and `ml==2.38.1` before queueing.

Runner selection is `['self-hosted', 'Windows', runner_label]`, with the configurable
label defaulting to `aifactory-admin-vm`. `defaults.run.shell` is `pwsh`.
Set `python_path` and `template_path` if installed locations differ.

From **Actions → Reusable Azure ML v2 factory → Run workflow**, select `validate`,
a scenario JSON path and optionally a runtime JSON path. Validation has only
`contents: read`; it requires no Azure/Kaggle credentials or network installation.

For `train` or `deploy`, configure federated Azure credentials and repository or
environment secrets:

- `AZURE_CLIENT_ID`
- `TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

`azure/login@v2` uses these values for OIDC. Only cloud jobs request `id-token: write`;
all jobs retain `contents: read`. Configure federation for the exact repository/ref
and, for deployment, the selected protected GitHub Environment subject.

`ingest` is a separate optional action using secret `KAGGLE_USERNAME`, `KAGGLE_KEY`
and/or `KAGGLE_API_TOKEN`. No terms/licenses are accepted automatically. Ingested data
remains on its runner; do not assume the next job is assigned to that same machine.
Upload via your approved data path and set runtime `input_data` before training.

Deployment additionally requires `deployment_environment`, `model_id`, matching
`scenario`/`mode` and optional `deployment_kind` (`online` or `batch`).
**Precreate the environment with required reviewers**, restrict allowed deployment
branches, and protect the credentials. GitHub can create an unprotected environment
when an arbitrary new name is used; this YAML cannot configure approvals for you.
Training never schedules deployment.

Reusable caller example (in a separately installed workflow):

```yaml
name: Manually validate a model
on: workflow_dispatch
permissions:
  contents: read
jobs:
  model:
    uses: ./.github/workflows/ml-factory.yml
    with:
      action: validate
      scenario: path\to\scenario.json
      runner_label: aifactory-admin-vm
```

A cloud caller must grant `id-token: write` and explicitly pass the three Azure
secrets above (or deliberately use `secrets: inherit`). Pin cross-repository reusable
workflow references to a reviewed commit SHA. Do not run untrusted fork code on a
credentialed self-hosted runner.