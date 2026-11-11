[Docs](../README.md) › Reference

# The six ESAF scenarios

Every tool runs the same six scenarios, and each scenario is one call. The app, the `azurefactory` CLI, the
Python SDK and REST are clients of the same Factory API, so the outcome is the same.

| Scenario | Python SDK | Outcome |
|---|---|---|
| 1. Init AI Factory | `esaf.init_factory()` | Starting from an empty subscription, creates the common part of the AI Factory, such as connectivity and private DNS zones, and the first project. |
| 2. Add scale set | `esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16")` | Prepares a new, empty Azure subscription by enabling resource providers, and creates the scale set's common resource group. |
| 3. Add or update project | `esaf.upsert_project("002", "dev")` | Creates the project's resource group and assigns team access. Adds or removes resources, changes settings such as SKUs, or creates the project if it doesn't exist. |
| 4. Delete project | `esaf.delete_project("002", "dev")` | Deletes the project's resource group. |
| 5. Delete scale set | `esaf.delete_scale_set("002", "dev")` | Deletes the project and common resource groups, leaving an empty Azure subscription. |
| 6. Delete AI Factory | `esaf.delete_factory()` | Deletes all project and common resource groups in every environment and removes the Factory's local configuration. Hub resource groups, Entra groups and Git repositories stay. |

Running a scenario is the approval: it changes Azure. Each scenario has a quickstart that runs it step by
step: [1](../quickstarts/02-create-factory.md), [2](../quickstarts/add-scale-set.md),
[3](../quickstarts/03-add-project.md) and [4 to 6](../quickstarts/05-clean-up.md).

## The same call in every tool

| Scenario | CLI | REST |
|---|---|---|
| 1 | `azurefactory esaf init-factory` | `POST /api/v1/esaf/init-factory` |
| 2 | `azurefactory esaf add-scale-set 002 dev --cidr 10.141.0.0/16` | `POST /api/v1/esaf/add-scale-set` |
| 3 | `azurefactory esaf upsert-project 002 dev` | `POST /api/v1/esaf/upsert-project` |
| 4 | `azurefactory esaf delete-project 002 dev` | `POST /api/v1/esaf/delete-project` |
| 5 | `azurefactory esaf delete-scale-set 002 dev` | `POST /api/v1/esaf/delete-scale-set` |
| 6 | `azurefactory esaf delete-factory` | `POST /api/v1/esaf/delete-factory` |

The CLI commands are the same in PowerShell and in Bash. Every REST body carries `"folder"` and
`"approved": true`. The API answers `202 Accepted` with a `job_id`.

## Parameters

| Parameter | Used by | What it does |
|---|---|---|
| `scale_set` | Scenarios 2 and 5; in 3 and 4 when the environment has more than one | Names the scale set, three digits as a string: `"002"`. |
| `project` | Scenarios 3 and 4 | Names the project, three digits as a string: `"002"`. |
| `environment` | Scenarios 2 to 5, required | Selects `"dev"`, `"stage"` or `"prod"`. A delete never reaches another environment. |
| `cidr` | Scenario 2 | Sets the new scale set's VNet range. The pipeline computes the subnets. |
| `max_projects` | Scenario 2 | Sets how many projects the scale set holds. The default is 7. |
| `subscription_id`, `tenant_id`, `orchestrator` | Scenario 2, Python and REST | Default to the environment's existing scale set. `orchestrator` is `"gha"` or `"ado"`. The CLI has no option for them. |
| `settings` | Scenarios 2 and 3 | In scenario 3, replaces the project settings you name; settings you leave out keep their value. In scenario 2, sets scale-set settings such as your own VNet and subnets. |
| `display_name` | Scenario 3 | Gives a new project a display name. |
| `include_project_subnets` | Scenario 4 | Also deletes the project's subnets. The default is `False`. |
| `include_keyvault_and_resource_group` | Scenario 4 | `False` deletes only the project's services. The default is `True`. |
| `creation_request` | Scenario 1 | Saves a new Factory and starts it in one call. Leave it out to run the draft you saved in the app. The CLI option is `--creation-request-json`. See [the example](../quickstarts/02-create-factory.md#describe-your-factory). |
| `retries` | All | Sets how often the API runs the scenario again after a failed run: 0 to 5, default 2. |
| `version_ref` | All | Deploys an explicit ESAF version instead of the Factory's own. |
| `wait`, `poll` | All, Python only | `wait=True` follows the job to its end and reads it every `poll` seconds. |

## Jobs

Each call returns a job at once. Follow it with `job.wait()`, `azurefactory esaf job <job ID> --wait` or
`GET /api/v1/esaf/jobs/{job_id}?folder=...`.

| Status | Meaning |
|---|---|
| `accepted`, `preparing`, `confirming`, `running`, `retrying` | The job is still going. |
| `succeeded` | The scenario finished. |
| `blocked` | A review refused it, or another job is running. Read `blockers`. |
| `failed` | The run failed after its retries. Read `problem`. |
| `interrupted` | The API stopped before the run started. Run the scenario again. |

The CLI exits with `0` when the job succeeded or is still running, `3` when it was blocked and `5` when it
failed.

## Errors

| Python exception | When |
|---|---|
| `ConfigError` | The target is unknown or ambiguous, `environment` is invalid, or `ESAF_FOLDER` isn't set. |
| `BlockedError` | The server's review refused the call, or another job is still running on the Factory. |
| `AuthError` | The API key is missing or wrong, or the API isn't on the same machine. |
| `FailureError` | The API failed, or its storage is unavailable. |

```python
from azurefactory import esaf
from azurefactory.errors import BlockedError, ConfigError

try:
    job = esaf.delete_project("002", "dev", wait=True)
except BlockedError as error:
    print("Refused:", error.message, error.details.get("blockers"))
except ConfigError as error:
    print("Check the call:", error.message)
```

**Next:** [Quickstart: Create your AI Factory](../quickstarts/02-create-factory.md)

Related: [ESAF usage guide](../../../environment_setup/azurefactory-cli/docs/esaf/readme.md) ·
[Guide 17: deletion prerequisites](../10-19/17-cli-and-api-and-usage.md) ·
[Maintainers: the step-by-step review flow](maintainers/automation-and-review-flow.md)
