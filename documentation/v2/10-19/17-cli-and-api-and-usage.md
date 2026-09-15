# Azure Factory CLI, Config Wizard API, and usage

Central cloud teams can use the **Azure Factory CLI**, its importable **Python
SDK**, or direct **HTTP requests** to integrate AI Factory configuration into
their own UX. These are clients of the Config Wizard API, not separate
implementations of Azure provisioning logic.

## Shared API: Tkinter and MAUI

The Tkinter application is the canonical backend. The MAUI build packages that
same Python API as a sidecar; it does not maintain an independent REST server.
Installed packages can still lag behind the source. Use the CLI's `doctor`
command to detect unsupported endpoints and contract differences.

For the example running instance:

- OpenAPI: <http://127.0.0.1:64979/openapi.json>
- Swagger: <http://127.0.0.1:64979/docs>
- Health: <http://127.0.0.1:64979/health>

MAUI chooses a loopback port dynamically. `64979` is an example, not a fixed
endpoint; the source API defaults to `8765`. Obtain the current URL and
`X-API-Key` from the authorized host/operator. Do not copy another process's
credentials. `/api/v1/schema` describes wizard fields; `/openapi.json` describes
the HTTP API.

The clients use catalog contract **1** and legacy deployment acknowledgement
**2**. Matching API version strings alone do not prove compatibility.

## Bootstrap distribution

The shared
[`bootstrap/01-aif-copy-aifactory-templates.sh`](../../../bootstrap/01-aif-copy-aifactory-templates.sh)
now copies the CLI/SDK and API examples alongside the existing infrastructure
and automation templates. Run it from the **consumer repository root** with
the `azure-enterprise-scale-ml` submodule present:

```bash
bash ./01-aif-copy-aifactory-templates.sh --auto
```

If the launcher has not been copied to the consumer root:

```bash
bash ./azure-enterprise-scale-ml/bootstrap/01-aif-copy-aifactory-templates.sh --auto
```

Both the default/`--auto` route and `--legacy-templates` produce:

```text
consumer-repository\
  azure-enterprise-scale-ml\                    Shared source submodule
  aifactory-templates\
    azurefactory-cli\
      readme.md
      pyproject.toml
      src\azurefactory\
      tests\
    install_config_wizard\
      api-usage-examples\
        readme.md
        scenarios.json
        requests\
        python\
        powershell\
        node\
        tests\
    config-wizard\                             Existing wizard placeholder
    ...
```

The two copied folders preserve their original relative layout, so links
between their guides continue to work. The CLI package source, example scripts,
scenario JSON templates, tests and local `.gitignore` files are included.
Virtual environments, caches, build output, `node_modules`, `.local` files,
review/confirmation receipts and unrelated operator files at the package root
are not distributed.

**Copying is not execution:** this step does not install the CLI, start an API,
authenticate to Azure, submit an API request or deploy infrastructure. Missing
CLI/example source assets stop the copier before it replaces existing templates;
copy failures are reported rather than presented as a successful sync.
The filtered copy uses the standard `find` and `tar` utilities available in Git
Bash and typical Linux/macOS shell environments; it does not require Python
merely to copy the CLI.

### Existing layout behavior is unchanged

| Bootstrap mode | Behavior |
|---|---|
| Default or `--auto` | Copies templates and the CLI/examples, while staging an inactive empty register under `aifactory-templates\azurefactory`. |
| `--legacy-templates` | Copies the same CLI/examples without nesting the new register starter into the legacy template layout. |
| `--init-azurefactory` | Initializes or preserves only `azurefactory\register.json`. It intentionally does **not** copy templates or the CLI/examples. |

The existing copier refuses active new-layout/mixed roots. If your consumer
already has an active `azurefactory` root, use the CLI/examples directly from
the submodule rather than forcing a legacy template sync.

Template sync replaces generated template copies on reruns. Keep customer UX
code, virtual environments, rendered requests and approval receipts **outside**
`aifactory-templates`. Do not treat that folder as the authoritative location
for your customizations. If the legacy bootstrap subsequently moves
`aifactory-templates` to `aifactory`, the two copied folders move with it and
retain their relative links.

## Install and connect the CLI

Python **3.10+** is required. The CLI/SDK has no third-party runtime dependencies.
From the consumer root, install into a dedicated environment outside the
replaceable template folder:

```powershell
python -m venv .venv-azurefactory
.\.venv-azurefactory\Scripts\Activate.ps1
python -m pip install .\aifactory-templates\azurefactory-cli

$env:AIFACTORY_API_URL = 'http://127.0.0.1:64979'
# Set AIFACTORY_API_KEY using your approved secret mechanism.
azurefactory health
azurefactory doctor
azurefactory --help
```

Alternatively, install directly from the shared source:

```powershell
python -m pip install .\azure-enterprise-scale-ml\environment_setup\azurefactory-cli
```

Use `python -m azurefactory` if the console command is not on PATH. A normal
package install is independent of later template replacement; reinstall when
you intentionally upgrade the copied package. Editable installs point at source
files and should not target a directory your bootstrap will replace.

All `folder`, `aifactory_folder`, `repo_root` and file-path arguments sent to the
API identify paths **on the API host**, not browser uploads. The API key grants
access to the local API; the host's Azure/GitHub/ADO identity and selected
tenant/subscription determine whether a requested operation can execute.

## CLI workflows

First inspect the exact factory/scale-set/project scope:

```powershell
$factoryFolder = 'C:\AIPlatform\azurefactory'
azurefactory catalog list --folder $factoryFolder
```

Use UUIDs returned by the catalog, not the first item or a guessed ID.
`DEV/001` and `STAGE/001` are different scale sets. Project numbers and scale-set
suffixes are three-digit strings, not UUIDs. Refresh IDs and the catalog revision
after each confirmed configuration change.

### Create a factory in a selected region

This command prepares **configuration only**, not Azure deployment:

```powershell
azurefactory factory create --folder $factoryFolder --factory-key central-ai-sweden `
  --prefix central- --region swedencentral --environment dev --suffix 001 `
  --subscription-id '<dev-subscription-uuid>' --tenant-id '<tenant-uuid>' `
  --orchestrator gha --vnet-cidr '<approved-dev-cidr>' --max-projects 3 `
  --save-receipt 'C:\AIPlatformReviews\create-factory.receipt.json'
```

Create the private review directory beforehand. Inspect the returned target,
effects, warnings, blockers, version and expiry, then obtain approval. Only in
that **separate approval step**:

```powershell
azurefactory catalog confirm --receipt 'C:\AIPlatformReviews\create-factory.receipt.json' --yes
```

Never put prepare and confirm into an unattended sequence merely because
`can_execute` is true. Receipts are expiring, scope-bound reviews, not permission
to skip your cloud team's approval policy.

### Supported scenarios and their boundaries

| Scenario | CLI/API approach |
|---|---|
| Clone factory X to region Y | `factory clone` with exact source UUID, new region/prefix, then `catalog confirm`. Copies configuration, not Azure resources, secrets, data or trained models. |
| Add a DEV scale set | `scaleset add --environment dev --suffix 002`, explicit tenant/subscription/network, then confirm. Registers configuration only. |
| Create a project in existing 001 | `project add --number 001 --placement dev=<DEV-001-UUID>`, then confirm. |
| Create a project in new 002 | First confirm creation of DEV/002; refresh its UUID/revision, then `project add --number 002 --placement dev=<DEV-002-UUID>`. Two separately reviewed writes. |
| Update a catalog project's resources | `parameters get`, then `parameters prepare` with exact published field names and both source/schema revisions; `parameters confirm`. Deployment is separate. |
| Promote a catalog project DEV to STAGE | Register STAGE scale set/placement as needed, review target parameters, then `runtime deploy` and separately `runtime confirm`. |
| Update a legacy project in DEV | `legacy plan --operation update --source-env dev --target-env dev`, then `legacy prepare` and separately `legacy start`. |
| Promote a legacy project to STAGE | `legacy plan --operation deploy --source-env dev --target-env stage`, then prepare/start. |
| Full new-factory bootstrap | `bootstrap prepare` with the GHA/ADO request, then separately `bootstrap start`. Includes common infrastructure **and** an initial project. |

Full bootstrap can create billable infrastructure, identities and repositories,
commit/push code and dispatch pipelines. It requires a new/empty destination;
it is not a substitute for adding a scale set to an existing factory.

Catalog runtime has explicit capability checks. Common-only creation, GHA
dispatch without supported atomic reviewed-commit handling, and unsupported
shared-remote bindings can be blocked. Honor those blockers; never reroute a
catalog operation through the legacy deployment API to bypass them. Legacy
deployment endpoints reject catalog roots.

The [CLI/SDK reference](../../../environment_setup/azurefactory-cli/readme.md)
contains the complete command syntax, receipt lifecycle, patch/version handling,
polling and exit-code behavior.

## API and Python SDK examples

The
[API example guide](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md)
provides 18 JSON request templates, their endpoint/model manifest, raw
PowerShell and Node.js consumers, Python rendering/parameter-patch helpers, a
read-only Python SDK example and curl equivalents.

From the consumer root, these copied scripts use the same connection environment:

```powershell
$examples = '.\aifactory-templates\install_config_wizard\api-usage-examples'

node "$examples\node\request.mjs" --path /health
pwsh -NoProfile -File "$examples\powershell\Request-AzureFactory.ps1" -Path /health

python "$examples\python\inspect_factory.py" --folder $factoryFolder `
  --factory-key central-ai-sweden --environment dev --suffix 001 --project-number 001 `
  --auth-status --parameters
```

Node.js **20+** or PowerShell **7+** is needed only for that respective raw
consumer. The Python SDK inspection example requires the installed CLI package.
It refuses ambiguous factory selections and mismatched project placements.

JSON templates contain `${VARIABLE}` placeholders. Use `render_request.py` to
substitute environment values safely in parsed JSON, rather than evaluating
shell expressions or concatenating JSON strings. Keep rendered output outside
the template destination. The API examples' `parameter_patch.py` builds a
single-field, revision-aware request from the current published parameter schema;
it does not guess resource field names or silently reset an existing profile.

## Integrate your own UX safely

Place the API key and SDK/HTTP client in your **trusted backend**, never in
browser JavaScript. The desktop sidecar is a local worker, not an authenticated
public multi-tenant control plane.

```text
User portal -> cloud-team backend -> local Config Wizard API -> reviewed operation
```

Your backend must authenticate the caller, authorize the exact factory and
tenant/subscription, restrict server-local paths, show the full preview, and
associate approval with the correct user and immutable review receipt. Use
isolated workers/identities when serving different customers.

Keep configuration and runtime consent separate. A timeout or Ctrl+C stops
local waiting, not the server job. Record job IDs and re-read state before
retrying a write. Legacy `submitted` means pipeline submission, not verified
Azure deployment success. Never log API keys, sensitive parameter values or
raw terminal output by default.