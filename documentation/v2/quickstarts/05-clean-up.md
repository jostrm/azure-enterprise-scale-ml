[Docs](../README.md) › [Quickstarts](README.md)

# Quickstart: Clean up

In this quickstart, you delete a project, a scale set or your whole AI Factory with one call each. A delete
removes the Azure resource groups that ESAF created, and nothing else.

> [!TIP]
> Prefer to watch first? The **ESAF Tutorials** lab guide plays narrated videos and checks your steps.
> [Download the ESAF Tutorials lab guide](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/install_tutorial_guide)
> (watch the videos inside it).

| Scenario | What goes | What stays |
|---|---|---|
| 4. Delete project | The project's resource group, with its Key Vault | Other projects, the scale set, the project's subnets |
| 5. Delete scale set | The scale set's project and common resource groups in that environment | Other scale sets, other environments |
| 6. Delete AI Factory | Every project and common resource group, and the Factory's local configuration | Hub resource groups, subscriptions, Entra groups, Git history |

## Prerequisites

- A Factory from [Quickstart: Create your AI Factory](02-create-factory.md).
- The Factory API running, and your tool connected. See [Quickstart: Install the ESAF tools](01-install-esaf.md).
- No other job running on the Factory. A second scenario waits until the first one ends.

## Delete what you no longer need

> [!CAUTION]
> A delete is permanent, and running it is the approval. Check the project number and the environment before
> you press Enter. A delete never reaches another environment.

Run only the lines you need. To remove everything, the last line is enough.

<details markdown="1" data-factory-tool="App" open>
<summary>App</summary>

1. In the app, select what you want to delete: a project, a scale set or the whole Factory.
2. Review the deletion plan, then confirm it.
3. Follow the run in the integrated terminal.

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

```powershell
azurefactory esaf delete-project 002 dev --wait
azurefactory esaf delete-scale-set 002 dev --wait
azurefactory esaf delete-factory --wait
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

```python
from azurefactory import esaf

job = esaf.delete_project("002", "dev", wait=True)
print(job.scenario, job.result["status"])
job = esaf.delete_scale_set("002", "dev", wait=True)
print(job.scenario, job.result["status"])
job = esaf.delete_factory(wait=True)
print(job.scenario, job.result["status"])
```

`wait=True` waits until the job ends, so each delete starts after the one before it.

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

In Git Bash, with `API_URL`, `API_KEY` and `FOLDER` set as in
[Quickstart: Create your AI Factory](02-create-factory.md#create-the-factory):

```bash
jq -n --arg folder "$FOLDER" '{folder: $folder, approved: true, project: "002", environment: "dev"}' |
  curl --silent --show-error --fail-with-body -X POST "$API_URL/api/v1/esaf/delete-project" \
    --header "X-API-Key: $API_KEY" --header 'Content-Type: application/json' --data @-
```

For a scale set, post `scale_set` and `environment` to `/api/v1/esaf/delete-scale-set`. For the whole
Factory, post only `folder` and `approved` to `/api/v1/esaf/delete-factory`:

```bash
jq -n --arg folder "$FOLDER" '{folder: $folder, approved: true}' |
  curl --silent --show-error --fail-with-body -X POST "$API_URL/api/v1/esaf/delete-factory" \
    --header "X-API-Key: $API_KEY" --header 'Content-Type: application/json' --data @-
```

</details>
<!-- /factory-tool -->

Two options change what a project delete removes:

| Option | What it does |
|---|---|
| `include_project_subnets=True`, or `--include-project-subnets` | Also deletes the project's subnets. |
| `include_keyvault_and_resource_group=False`, or `--keep-keyvault-and-resource-group` | Deletes only the project's services and keeps its Key Vault and resource group. |

You don't grant a deletion permission first. The API grants it once for the Factory, then runs the delete.

## Verify the result

Each job ends with status `succeeded`. After a Factory delete, the resource groups are gone:

```powershell
az group list --subscription <your Dev subscription ID> --query "[].name" --output table
```

Expected output: no resource group that starts with your Factory's prefix.

| Job status | What to do |
|---|---|
| `blocked` | Another job is still running on the Factory, or a review refused the delete. Read `blockers` in the job. |
| `failed` | Read `problem` in the job, then run the same call again. Deletes that are already done are skipped. |

## Clean up resources

A Factory delete keeps what other teams may share. Remove these yourself when you no longer need them:

- The hub resource groups, if you created a hub only for this Factory.
- The Microsoft Entra groups and the Agent Chat sign-in registration.
- Your consumer repository.

Then close the app. That stops the Factory API.

## Next step

**Next:** [Usage docs - project team](../usage/README.md)

Related:

- [Guide 20: Remove, observe and recover](../10-19/20-cli-and-api-and-usage.md): review a delete before it
  runs, or recover a stopped job.
- [The six scenarios](../reference/scenarios.md): every call and its parameters.
