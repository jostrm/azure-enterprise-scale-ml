# Parameters: configure your factory

**Parameters** are the settings called variables in `variables.json`, ADO
`variables.yaml` and GitHub `.env` files. Use this section to find the correct
name, value and dependency for the route you are using.

| What you need | Open |
| --- | --- |
| Start configuring a registered factory | [CLI, Python SDK or REST tutorial](../factory-tools/18-cli-and-api-and-usage.md) |
| Know which inputs to collect | [Required inputs](standard.md) |
| Look up an exact key, default or format mapping | [All parameters](advanced.md) |
| Change settings and deploy separately | [Add and update](../factory-tools/19-cli-and-api-and-usage.md) |
| Remove an override, draft or Azure resource | [Remove and recover](../factory-tools/20-cli-and-api-and-usage.md) |

!!! important "A saved setting is not a deployment"
    Review and save your configuration first. Deployment needs a separate
    approved operation. Turning a flag off or removing a parameter override
    is not a general resource-deletion instruction.

## Recommended: let the registered-factory tools save settings

For a registered factory, read the available settings and choose the exact
factory/project/environment before editing. Use the named CLI or SDK helpers,
or the matching REST request.

| Task | CLI | Python SDK | REST |
| --- | --- | --- | --- |
| Read editable settings | `catalog settings` | `catalog_settings(...)` | `GET /api/v1/factory-catalog/settings` |
| Prepare setting replacements | `catalog configure-settings` | `catalog_settings_prepare(...)` | `POST /api/v1/factory-catalog/prepare`, action `configure-settings` |
| Save reviewed replacements | `catalog confirm` | `catalog_confirm(...)` | `POST /api/v1/factory-catalog/confirm` |
| Read deployed-template parameter choices | `parameters get` | `catalog_parameters(...)` | `GET /api/v1/factory-catalog/parameters` |
| Prepare typed parameter changes | `parameters prepare` | `parameter_prepare(...)` | `POST /api/v1/factory-catalog/parameters/prepare` |
| Save reviewed parameter changes | `parameters confirm` | `parameter_confirm(...)` | `POST /api/v1/factory-catalog/parameters/confirm` |

These are command/method names, not complete examples. The
[tool-specific tutorial](../factory-tools/19-cli-and-api-and-usage.md) provides
full examples with required inputs and separate confirmation.

The API writes the registered project files. Do not hand-edit `register.json`,
review files or generated project exports to bypass validation. Changing a
factory default does not necessarily change an existing project's saved settings.

## Dev, Stage and Prod

A generated registered project's `variables.json` has `dev` and `stage_prod`
sections. Stage and Prod use their own selected subscriptions but share the
Stage/Prod settings section. Review both environments before changing shared
values. A placement selects a real registered scale set; it does not create a
subscription or move deployed resources.

The checked-in [shared JSON template](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/variables.json)
currently contains **`dev` only**, including paired Dev/StageProd fields.
It is a template reference, not the full registered project's storage format.

## Feature choices to review together

| Area | Parameters and guidance |
| --- | --- |
| Private Foundry agents | Review `enableAIFoundry`, `enableAFoundryCaphost`, Search, Cosmos DB and Storage dependencies together. A simple preset and raw template defaults are not interchangeable. |
| Network and DNS | Select your address plan and whether DNS/network services are standalone, factory-owned or provided centrally. Flags alone do not establish private access. |
| Models and compute | Choose the version, SKU and capacity supported in the selected region/subscription. A default is not reserved capacity. |
| MCP and gateways | Factory MCP, dedicated AI Gateway, regular APIM/Kong and Application Gateway are distinct choices. See [the current parameter guide](advanced.md#mcp-and-ai-gateway-parameters). |
| Access | Existing group/object IDs, managed identities, role assignments and secret-name references have different meanings. Do not put credential values in these files. |
| Deletion | Use the separate reviewed removal flow; ordinary settings replacements cannot request arbitrary destructive actions. |

## Optional project ownership labels

`org-department-name` and `org-department-id` describe who owns a project. Both
default to an empty string. Keep them consistent across that project's
environments. They do not grant permissions, change identity or automatically
write Azure resource tags.

<details markdown="1">
<summary>More info</summary>

The name supports plain Unicode text up to 200 characters; the ID is a string
up to 128 characters, not necessarily a GUID. Control characters are rejected.
JSON/YAML use the hyphenated names; `.env` uses `ORG_DEPARTMENT_NAME` and
`ORG_DEPARTMENT_ID`. Read/edit them at project scope, not as an inherited factory
label.

The [generated reference](advanced.md#source-coverage) reads shared repository
templates, not a customer's files. It lists actual assigned values and explicit
format mappings. A template-only field may still be rejected by an older API.
The selected host's `/api/v1/schema` describes editor fields; `/openapi.json`
describes HTTP requests; `parameters get` describes the selected published
deployment templates. These are different schemas.

</details>

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

For a consumer-owned legacy JSON file, you may edit the exact input used by its
pipeline. Preserve other keys, value types and environments, and review the
effective result. Updating `.env`, YAML and JSON independently can create
conflicting inputs; remote GitHub variables have their own publication step.

Legacy `config review/save` and `ConfigurationDraft` preserve a persistent JSON
project's source information. They are not registered catalog save commands.
The legacy HTTP routes include `/api/v1/projects/load`, `/api/v1/import`,
`/api/v1/validation`, `/api/v1/export` and `/api/v1/projects/save`.
Export can write a host-local file when a path is supplied; it does not deploy.

The pipeline JSON reader can overlay `dev`, `stage_prod`, then exact `test` or
`prod` sections. That entry-point-specific behavior does not permit adding those
sections to a registered project snapshot. See the
[file-first versus wrapper-first guidance](../factory-tools/18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).

The API is an administrative service with local-host restrictions, not a public
ticket-system endpoint. Keep keys on an approved backend/worker, not in browser
JavaScript. Authentication, Azure/provider permissions and operation approval
remain separate.

</details>
