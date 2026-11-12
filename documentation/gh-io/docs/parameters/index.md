# Parameters: configure your factory

**Parameters** are the settings of a Factory and its projects. They are the variables in `variables.json`,
and they have matching names in the Azure DevOps `variables.yaml` and in the GitHub `.env` file. Use this
section to find the name of a setting, its values and what it depends on.

| What you need | Open |
| --- | --- |
| Start configuring a Factory | [CLI, Python SDK or REST tutorial](../factory-tools/18-cli-and-api-and-usage.md) |
| Choose the Azure services of a project | [Azure resource library](../resources/index.md) |
| See every variable in `variables.json`, with its default and what it does | [Every variable in variables.json](variables.md) |
| Know which inputs to collect | [Required inputs](standard.md) |
| Look up an exact key, default or format mapping | [All parameters](advanced.md) |
| Change settings and deploy them | [Add and update](../factory-tools/19-cli-and-api-and-usage.md) |
| Delete a project, a scale set or a Factory | [Clean up](../setup/05-clean-up.md), [Remove and recover](../factory-tools/20-cli-and-api-and-usage.md) |

!!! important "Switching a service off"
    A service set to `"false"` is no longer deployed. A resource that already exists stays in Azure while
    `enableDeleteForDisabledResources` is `"false"`, the default. With `"true"`, the next run of the project
    pipeline deletes the switched-off services that exist in the project resource group, and it purges
    Foundry, AI Services, Azure OpenAI and Azure Machine Learning resources. It keeps Key Vault, storage,
    Application Insights and managed identities. See
    [what happens when you switch a service off](../index.md#what-happens-when-you-switch-a-service-off).

## Change settings with a tool

Read the settings of the Factory, the project and the environment you mean before you change them. The
quickest way is one call, such as `esaf.upsert_project(..., settings=...)`: see
[the six scenarios](../reference/scenarios.md). To review each change before it is saved, use these commands.

| Task | CLI | Python SDK | REST |
| --- | --- | --- | --- |
| Read editable settings | `catalog settings` | `catalog_settings(...)` | `GET /api/v1/factory-catalog/settings` |
| Prepare setting replacements | `catalog configure-settings` | `catalog_settings_prepare(...)` | `POST /api/v1/factory-catalog/prepare`, action `configure-settings` |
| Save reviewed replacements | `catalog confirm` | `catalog_confirm(...)` | `POST /api/v1/factory-catalog/confirm` |
| Read deployed-template parameter choices | `parameters get` | `catalog_parameters(...)` | `GET /api/v1/factory-catalog/parameters` |
| Prepare typed parameter changes | `parameters prepare` | `parameter_prepare(...)` | `POST /api/v1/factory-catalog/parameters/prepare` |
| Save reviewed parameter changes | `parameters confirm` | `parameter_confirm(...)` | `POST /api/v1/factory-catalog/parameters/confirm` |

The table gives the names only. [Add and update](../factory-tools/19-cli-and-api-and-usage.md) has a full
example for each one.

The Factory API writes `register.json` and the `variables.json` of each project. Change them with a tool, so
that the API checks every value. A project keeps its own saved settings: changing a default of the Factory
changes new projects only.

## Dev, Stage and Prod

The `variables.json` of a project has two sections: `dev`, and `stage_prod` for Stage and Prod. Stage and Prod
have their own subscriptions and share the settings of `stage_prod`, so a change there reaches both.

The [template of variables.json](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/variables.json)
in the repository has a `dev` section only. It holds the Dev and the Stage/Prod value of each SKU side by side.

## Settings that belong together

| Area | Settings |
| --- | --- |
| Private Foundry agents | `enableAIFoundry` and `enableAFoundryCaphost` need AI Search, Cosmos DB and Storage. Switch them on together. |
| Network and DNS | The address range, and where the private DNS zones live: in the Factory or in your hub. See [Hub and network modes](../reference/hub-and-network-modes.md). |
| Models and compute | The model version, the SKU and the capacity. What you can choose depends on the region and on your quota. |
| MCP and gateways | The Factory MCP server, the AI gateway on API Management or Kong, and Application Gateway each have their own settings. See [MCP and AI gateway](advanced.md#mcp-and-ai-gateway-parameters). |
| Access | Entra ID object IDs of users or groups, and the names of Key Vault secrets. A setting holds the name of a secret, never the secret itself. |
| Deletion | `enableDeleteForDisabledResources` for switched-off services. [Clean up](../setup/05-clean-up.md) for a whole project, scale set or Factory. |

## Optional project ownership labels

`org-department-name` and `org-department-id` say who owns a project. Both are empty by default. Use the same
values in every environment of the project. They are labels only: they change no access and no Azure tags.

<details markdown="1">
<summary>More info</summary>

The name supports plain Unicode text up to 200 characters; the ID is a string
up to 128 characters, not necessarily a GUID. Control characters are rejected.
JSON/YAML use the hyphenated names; `.env` uses `ORG_DEPARTMENT_NAME` and
`ORG_DEPARTMENT_ID`. Read/edit them at project scope, not as an inherited factory
label.

The [generated reference](advanced.md#source-coverage) is built from the templates in the repository. It
lists the default of every setting and its name in each format. An older Factory API can lack a setting that
is new in the templates. `/api/v1/schema` lists the settings your API knows, `/openapi.json` lists its HTTP
requests, and `parameters get` lists the settings of the deployed templates.

</details>

<details markdown="1">
<summary>Earlier way: edit the files of a v1.24 repository (Legacy)</summary>

In a repository that was set up with v1.24, you edit the file that its pipeline reads. Keep the other keys,
the value types and the environments as they are. Change a setting in one format only, because the `.env`
file, the YAML and the JSON are separate inputs. GitHub variables are published by their own step.

The commands `config review` and `config save`, and the routes `/api/v1/projects/load`, `/api/v1/import`,
`/api/v1/validation`, `/api/v1/export` and `/api/v1/projects/save`, work on such a JSON file. Export writes a
file on the machine that runs the API. It doesn't deploy.

The pipeline reads the `dev` section first, then `stage_prod`, then a `test` or `prod` section when one
exists. See
[file first or wrapper first](../factory-tools/18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).

The Factory API is an administration service that listens on the local machine. Keep its key on a server you
trust, never in browser JavaScript.

</details>
