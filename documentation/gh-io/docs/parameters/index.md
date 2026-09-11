# Configuration and API

Keep each project's complete configuration together. The current JSON format has
two sections: **`dev`** and **`stage_prod`**. It includes shared settings,
environment-specific choices, all three subscription IDs, and factory/project
naming. GitHub Actions `.env` and Azure DevOps `variables.yaml` remain supported;
their names are not always identical.

| Reference | Use |
|---|---|
| [Standard parameters](standard.md) | Required and conditional setup inputs |
| [All variables](advanced.md) | Current configuration keys, route-specific names, defaults and guidance |
| [GitHub Actions](../orchestrators/gh.md) | Create/update scripts and workflow configuration |
| [Azure DevOps](../orchestrators/ado.md) | Create/update scripts and service connections |

## One project, all environments

```text
project006\
  project_state.json
  variables.json
```

`project_state.json` is the configuration API's saved editor state.
`variables.json` is the pipeline configuration. Do not pass editor-only state keys
directly to a pipeline. The following is a **structural excerpt**, not a complete
deployable configuration:

```json
{
  "dev": {
    "project_number_000": "006",
    "admin_aifactoryPrefixRG": "team-",
    "admin_aifactorySuffixRG": "-001",
    "dev_sub_id": "<dev-subscription-id>",
    "test_sub_id": "<stage-subscription-id>",
    "prod_sub_id": "<prod-subscription-id>"
  },
  "stage_prod": {
    "project_number_000": "006",
    "admin_aifactoryPrefixRG": "team-",
    "admin_aifactorySuffixRG": "-001",
    "dev_sub_id": "<dev-subscription-id>",
    "test_sub_id": "<stage-subscription-id>",
    "prod_sub_id": "<prod-subscription-id>"
  }
}
```

Dev execution selects `dev`; Stage and Prod select `stage_prod` and their
respective subscription. The shared Stage/Prod section must represent both
environments consistently. Changing a subscription reference does not create or
move a subscription. Changing networking in a file does not migrate a deployed VNet.

Use the full [JSON template](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/variables.json)
as the field reference and preserve its property names and value types. That
raw source template currently contains only `dev`; generated project configuration
has both sections. See [the exact format distinction](advanced.md#scope-and-authoritative-sources).
Route adapters translate JSON
into the pipeline's expected variables. Updating `.env`, YAML and JSON separately
can leave conflicting settings: choose the intended input explicitly for each run.
Never commit populated credentials, protected artifacts or private configuration.

### Optional project organizational ownership

`org-department-name` and `org-department-id` are optional project metadata, both
defaulting to `""`. Keep the same values in `dev` and `stage_prod` within that
project's full `variables.json`; conflicting values require explicit correction.
Older configurations without either key remain supported. Neither field inherits
from the factory or another project, and neither changes cost center, identity,
authentication or authorization. The name accepts Unicode plain text (up to 200
characters); the ID is a string (up to 128 characters), not necessarily a GUID.
Control characters are not allowed.

JSON and YAML retain these exact hyphenated keys. Shell `.env` uses
`ORG_DEPARTMENT_NAME` and `ORG_DEPARTMENT_ID`; quote values as shell literals.
These fields are configuration metadata only, not automatically written to Azure
resource tags. Existing cost-center tags and department tag aliases remain separate.

## API layer

An API-enabled installation exposes configuration, validation and reviewed
operations independently of the calling application. The default local endpoint
is `http://127.0.0.1:8765`; deployed host ports may differ.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Public process health; not Azure deployment status |
| `GET /docs` and `/openapi.json` | Running API's interactive reference and exact request schemas |
| `GET /api/v1/schema` | Configuration keys, defaults and choices; not the OpenAPI document |
| `POST /api/v1/import` | Import JSON, YAML or `.env` into configuration state |
| `POST /api/v1/validation` | Validate supplied current-project state without saving or deploying |
| `POST /api/v1/export` | Render JSON, YAML or `.env`; a requested output path writes a file |
| `POST /api/v1/projects/save` | Save project configuration; pipeline-variable writes are explicit |
| `GET /api/v1/creation/capabilities` | Supported create launchers and typed bootstrap fields |
| `POST /api/v1/creation/bootstrap/prepare` | Review common-infrastructure plus initial-project creation |
| `POST /api/v1/creation/bootstrap/start` | Execute the reviewed bootstrap confirmation |
| `/api/v1/operations/project-deployments/plan`, `/prepare`, `/start` | Save a deployment draft, review it, then explicitly execute |

All `/api/v1/*` requests require `X-API-Key`, configured on the host through
`AIFACTORY_API_KEY`. Execution additionally requires the appropriate host identity,
permissions, tools and current published scripts. Use the live OpenAPI schemas:
configuration `state`, a bootstrap `config`, and a pipeline `variables.json` are
different request formats, not interchangeable objects.

Preparation is not execution. Keep the returned confirmation tied to its exact
factory, project, environment and version; changed or expired inputs need a fresh
review. Poll the returned job ID rather than blindly retrying a start request.
Address-planning findings are advisory; authentication, identity, schema and
execution prerequisites remain separate.

## Two common workflows

- **ITSM-integrated:** ServiceNow, Jira Service Management or an internal portal
  can call the API through a trusted automation runner: import/configure,
  validate, prepare, apply the organization's approval policy, execute and track
  the job. Unattended execution requires pre-established authentication and all
  required inputs; an incoming ticket alone is not deployment authorization.
- **Core-team managed:** The core team maintains the project configuration and
  runs the appropriate [GHA](../orchestrators/gh.md) or
  [ADO](../orchestrators/ado.md) create/update Bash launcher on the team's behalf.

!!! warning "API access"
    The local API is loopback-scoped, not a public ITSM endpoint. Do not expose
    its port or put API keys in URLs. Use an authenticated integration on the
    intended execution host, with protected secret storage and least privilege.

## Template guidance

Source comments use `<mandatory>`, `<optional>`, `<default>`, `<ensure>`,
`<recommended>`, `<keep-as-is>` and `<otherwise>` tags. Requirements can be
conditional on a selected feature; template defaults are not proof of deployment
readiness. Consult the generated [complete reference](advanced.md) for the exact
source values and differences between formats.
