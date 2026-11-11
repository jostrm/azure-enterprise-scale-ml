[Docs](../README.md) › [Quickstarts](README.md)

# Quickstart: Add a project for your team

In this quickstart, you add a project for a team with one call, then change one of its settings with the same
call. A **project** is one team's own resource group, with its AI services and its access group.

> [!TIP]
> Prefer to watch first? The **ESAF Tutorials** lab guide plays the narrated video for this scenario and
> checks your steps. [Download the ESAF Tutorials lab guide](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/install_tutorial_guide)
> (watch the videos inside it).

<img src="../images/concepts/scale-set-floor.svg" width="640" alt="Illustration of a factory building where each floor is a scale set that holds project rooms.">

*AI-generated illustration.*

A **scale set** is one floor of the Factory: a network and a subscription that hold up to seven projects by
default. Your Factory starts with scale set 001 in Dev.

## Prerequisites

- A Factory from [Quickstart: Create your AI Factory](02-create-factory.md).
- The Factory API running, and your tool connected. See [Quickstart: Install the ESAF tools](01-install-esaf.md).
- A free three-digit project number, for example `002`.

## Add the project

"Upsert" means add or update. A new project is registered and deployed. An existing project gets its settings
saved and is deployed again.

<details markdown="1" data-factory-tool="App" open>
<summary>App</summary>

1. In the app, open **Projects**.
2. Add project `002` to the Dev scale set 001.
3. Review the plan, then confirm it.
4. Follow the run in the integrated terminal.

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

```powershell
azurefactory esaf upsert-project 002 dev --wait
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

```python
from azurefactory import esaf

job = esaf.upsert_project("002", "dev")
state = job.wait()
print(state["status"], "-", state["message"])
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

In Git Bash, with `API_URL`, `API_KEY` and `FOLDER` set as in
[Quickstart: Create your AI Factory](02-create-factory.md#create-the-factory):

```bash
jq -n --arg folder "$FOLDER" '{folder: $folder, approved: true, project: "002", environment: "dev"}' |
  curl --silent --show-error --fail-with-body -X POST "$API_URL/api/v1/esaf/upsert-project" \
    --header "X-API-Key: $API_KEY" --header 'Content-Type: application/json' --data @-
```

</details>
<!-- /factory-tool -->

The run takes 25 to 30 minutes.

## Change a setting

Send the same call with the settings you want to change. Settings you leave out keep their value.

<details markdown="1" data-factory-tool="App" open>
<summary>App</summary>

1. In the app, open **Projects** and select project `002`.
2. Change the setting, for example the cost center tag.
3. Review the plan, then confirm it.

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

```powershell
'{"tag_costcenter": "lab"}' | Set-Content .\project-settings.json
azurefactory esaf upsert-project 002 dev --settings-json .\project-settings.json --wait
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

```python
from azurefactory import esaf

job = esaf.upsert_project("002", "dev", settings={"tag_costcenter": "lab"})
print(job.wait()["status"])
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

```bash
jq -n --arg folder "$FOLDER" \
  '{folder: $folder, approved: true, project: "002", environment: "dev", settings: {tag_costcenter: "lab"}}' |
  curl --silent --show-error --fail-with-body -X POST "$API_URL/api/v1/esaf/upsert-project" \
    --header "X-API-Key: $API_KEY" --header 'Content-Type: application/json' --data @-
```

</details>
<!-- /factory-tool -->

| Parameter | What it does |
|---|---|
| `project` | Sets the project number, three digits as a string: `"002"`. |
| `environment` | Selects `"dev"`, `"stage"` or `"prod"`. It's required. |
| `scale_set` | Selects the scale set. You need it only when the environment has more than one. |
| `settings` | Replaces the settings you name. |
| `display_name` | Gives a new project a display name. |

## Verify the result

The job ends with status `succeeded`, and your folder holds the new project:

```text
azurefactory\factories\<your factory>\scalesets\001\projects\project002\variables.json
```

In Azure, you see one more resource group, for project 002.

If the call is refused:

| Message | Fix |
|---|---|
| `More than one dev scale set matches; pass scale_set.` | Name the scale set: `--scale-set 001` or `scale_set="001"`. |
| `environment must be dev, stage or prod` | Use one of the three names, in lower case. |
| A job stays `blocked` | Read `blockers` in the job, fix what they name, and run the call again. |

## Clean up resources

Delete the project when the team no longer needs it:

| Tool | Call |
|---|---|
| CLI | `azurefactory esaf delete-project 002 dev --wait` |
| Python SDK | `esaf.delete_project("002", "dev")` |
| REST | `POST /api/v1/esaf/delete-project` |

See [Quickstart: Clean up](05-clean-up.md).

## Next step

**Next:** [Quickstart: Create your first agent by enabling ESAF Agent Chat](04-first-agent-chat.md)

Related:

- [The six scenarios](../reference/scenarios.md): add a scale set when a floor is full.
- [Usage docs](../usage/README.md): hand the project over to the team.
- [Microsoft Entra groups and personas](../10-19/16-ad-groups-personas.md): who gets access to a project.
