# Azure DevOps installation

This is an opt-in **stages template**, not an installed pipeline. After provisioning
the runner as described in the parent README, create your own caller:

```yaml
trigger: none
pr: none
parameters:
  - name: action
    type: string
    default: validate
    values: [validate, ingest, train, deploy]
extends:
  template: copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/ado/ml-factory.yml
  parameters:
    action: ${{ parameters.action }}
    poolName: YOUR_SELF_HOSTED_POOL
    agentName: YOUR_REGISTERED_AGENT
    serviceConnection: YOUR_AZURE_SERVICE_CONNECTION
    scenario: path\to\scenario.json
    runtime: path\to\runtime.json
    mode: custom
```

Install that caller through **Pipelines → New pipeline → Existing YAML**, then manually
queue `validate` first. Supply the existing self-hosted pool, exact agent name and
service connection from your project configuration; no project values are hardcoded.
AzureCLI@2 uses `pscore` and the selected connection only in cloud stages.
An offline caller may leave `serviceConnection` empty.

Queue `ingest` only after manual Kaggle licensing approval. Define secret variables
`KAGGLE_USERNAME`, `KAGGLE_KEY` and/or `KAGGLE_API_TOKEN`; define unused values as empty
so unresolved Azure DevOps macro strings are not mistaken for credentials. Never
place credentials in YAML or runtime JSON.

Queue `train` separately when runtime `input_data` is ready. It validates, renders
`pipeline.yml`, submits/polls with preinstalled `ml==2.38.1`, and registers only a
successfully evaluated model. It publishes the registration receipt, not datasets.

To queue **deploy**, additionally provide `modelId` (an immutable evaluated version),
`deploymentEnvironment` (an existing environment with approval/check policies), and
optionally `deploymentKind: online|batch`. Keep `mode` and `scenario` consistent with
the registered model. The deploy stage depends only on validation and is included
only when the explicit action is `deploy`; training never selects it automatically.
Restrict environment creation/use and protect production independently.

Optional path overrides: `pythonPath`, `templatePath`. Provisioning, environment
approvals, service-connection authorization, compute/data permissions and private
network connectivity are administrator prerequisites, not pipeline side effects.