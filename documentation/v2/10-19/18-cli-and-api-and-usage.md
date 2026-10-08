# 18. Get started with Factory tools

[19: Add and update](19-cli-and-api-and-usage.md) |
[20: Remove and recover](20-cli-and-api-and-usage.md)

Choose one tool below. The whole tutorial changes with your choice on the
[documentation site](https://jostrm.github.io/azure-enterprise-scale-ml/factory-tools/18-cli-and-api-and-usage/).
GitHub's Markdown viewer provides expandable tool sections instead of interactive tabs.

**This quick connection check does not create Azure resources, deploy or delete.**
It uses the new registered Azure Factory approach and an empty local folder.
You need the prepared API and accelerator source folders from your platform team.

## Choose your tool

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

The **CLI** gives you ready-made commands to type in PowerShell. Start here
if you do not want to write a program.

### 1. Start the local demo service in Window A

Open PowerShell. Enter your prepared API folder when asked.

```powershell
$ErrorActionPreference = 'Stop'
$ApiRoot = Read-Host 'Full path to the prepared API folder'
$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Ask your platform team to complete API setup first.'
}
Set-Location -LiteralPath $ApiRoot
$env:AIFACTORY_API_KEY = 'local-parity-smoke-only'
& $Python -m uvicorn src.api:app --host 127.0.0.1 --port 8876
```

Leave Window A running. The example key is **only for this local demo**.
Do not use it for a real factory.

### 2. Set up Window B

Open a **second PowerShell window** and paste this entire block.
Variables are not shared between windows.

```powershell
$ErrorActionPreference = 'Stop'
$ApiRoot = Read-Host 'API folder used in Window A'
$AcceleratorRoot = Read-Host 'Accelerator source folder'
$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$SdkSource = Join-Path $AcceleratorRoot 'environment_setup\azurefactory-cli\src'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $SdkSource 'azurefactory\client.py'))) {
    throw 'Check the API and accelerator folders.'
}
$env:PYTHONPATH = $SdkSource
$env:AIFACTORY_API_URL = 'http://127.0.0.1:8876'
$env:AIFACTORY_API_KEY = 'local-parity-smoke-only'
$DemoRoot = Join-Path $env:TEMP ('factory-smoke-' + [guid]::NewGuid())
$env:FACTORY_FOLDER = Join-Path $DemoRoot 'azurefactory'
New-Item -ItemType Directory -Path $env:FACTORY_FOLDER | Out-Null
```

### 3. Check the connection

```powershell
& $Python -m azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'The service is not reachable.' }
& $Python -m azurefactory catalog list --folder $env:FACTORY_FOLDER
if ($LASTEXITCODE -ne 0) { throw 'The factory list could not be read.' }
```

Expect a healthy service and an empty factory list. You have not created a
factory yet. **You are finished; no developer tests are required.**
Stop the idle demo service with **Ctrl+C in Window A**.

<details markdown="1">
<summary>More info</summary>

If port 8876 is busy, use a free port in **both** windows; do not stop an
unrelated service. `127.0.0.1` means your own computer. The normal API source
default is 8765; a desktop app can use a different port.

Optional compatibility information, while Window A is running:

```powershell
& $Python -m azurefactory doctor
& $Python -m azurefactory schema --openapi
& $Python -m azurefactory bootstrap capabilities
```

These checks do not guarantee that an Azure deployment will succeed.
Python is used here to launch the existing CLI package without requiring a
separate `azurefactory.exe` installation.

</details>

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

The **SDK** provides Python helpers for your scripts or applications.
These are ordinary Python examples: save them as `.py` files or run them
in your Python editor. No PowerShell strings are involved.

### 1. Start the local demo service

If your platform team already started the demo service, go to step 2.
Otherwise save this as `start_factory_demo.py`. In your editor, select the
prepared API folder's `.venv` Python interpreter, then run this file.

```python
import os
from pathlib import Path
import sys
import uvicorn

api_root = Path(input("Prepared API source folder: ").strip()).resolve()
if not (api_root / "src" / "api.py").is_file():
    raise SystemExit("Select the prepared API source folder.")

os.chdir(api_root)
sys.path.insert(0, str(api_root))
os.environ["AIFACTORY_API_KEY"] = "local-parity-smoke-only"
uvicorn.run("src.api:app", host="127.0.0.1", port=8876)
```

Leave it running. The key above is **for this empty local demo only**.

### 2. Run a real Python example

Open another editor terminal or Python process. Save this as
`factory_smoke.py` and run it with Python 3.10 or later.
Enter the accelerator source folder and the demo key when asked.
You can also use the [ready-to-run Python file](../../../environment_setup/install_config_wizard/api-usage-examples/python/factory_smoke.py).

```python
import getpass
import json
from pathlib import Path
import sys
import tempfile

accelerator = Path(input("Accelerator source folder: ").strip()).resolve()
sdk_source = accelerator / "environment_setup" / "azurefactory-cli" / "src"
if not (sdk_source / "azurefactory" / "client.py").is_file():
    raise SystemExit("The selected folder does not contain the Factory SDK.")
sys.path.insert(0, str(sdk_source))

from azurefactory import AzureFactoryClient

url = input("Demo API URL [http://127.0.0.1:8876]: ").strip() or "http://127.0.0.1:8876"
key = getpass.getpass("Demo API key: ")
if not key:
    raise SystemExit("Enter the local demo key.")
client = AzureFactoryClient(base_url=url, api_key=key)

print(json.dumps(client.health(), indent=2))
folder = Path(tempfile.mkdtemp(prefix="factory-smoke-")) / "azurefactory"
folder.mkdir()
print(f"Empty local demo folder: {folder}")
print(json.dumps(client.catalog_list(str(folder)), indent=2))
```

Expect a healthy service and an empty factory list. **No extra test step is
required.** Stop your idle demo service when finished.

<details markdown="1">
<summary>More info</summary>

The SDK sends HTTP requests to the API service; it does not replace that
service. This example imports the reviewed SDK source without installing
packages. The SDK itself uses Python's standard library.

If the package is already installed in your selected interpreter, omit the
source-folder prompt and `sys.path` setup and start with:

```python
from azurefactory import AzureFactoryClient

client = AzureFactoryClient()  # Uses AIFACTORY_API_URL and AIFACTORY_API_KEY.
print(client.health())
```

Set those environment variables through your approved secret mechanism.
Do not put a real API key in a Python file or notebook you share.
The local temporary folder works because the API runs on the same computer.

</details>

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

**REST** lets you send requests directly, without the Factory CLI or Python
SDK. This example uses **Bash and curl**. On Windows, use Git Bash, not
PowerShell, for the commands in this tab.

### 1. Connect to the prepared demo service

Ask your platform team to start the local demo API, or use the optional
startup instructions below. Keep the service running while trying step 2.

<details markdown="1">
<summary>More info</summary>

To start the prepared API yourself from **Git Bash on Windows**, enter its
Windows folder path. `cygpath` converts the path for Git Bash:

```bash
read -r -p "Prepared API folder (Windows path): " api_windows
api_root="$(cygpath -u "$api_windows")"
cd "$api_root" || exit 1
AIFACTORY_API_KEY='local-parity-smoke-only' \
  .venv/Scripts/python.exe -m uvicorn src.api:app --host 127.0.0.1 --port 8876
```

Leave this terminal running and use another Git Bash terminal for step 2.
On Linux/macOS, start the service from its prepared environment instead;
the following curl requests are unchanged.

</details>

### 2. Set the address, key and empty local folder

Use the address/key of the **local demo**, not a production factory.
`curl` must support `--fail-with-body`.

```bash
read -r -p "Demo API URL [http://127.0.0.1:8876]: " API_URL
API_URL="${API_URL:-http://127.0.0.1:8876}"
API_URL="${API_URL%/}"
read -r -s -p "Demo API key: " API_KEY
printf '\n'
test -n "$API_KEY" || { printf 'An API key is required.\n' >&2; exit 1; }

demo_root="$(mktemp -d)"
mkdir "$demo_root/azurefactory"
if command -v cygpath >/dev/null 2>&1; then
  FACTORY_FOLDER="$(cygpath -w "$demo_root/azurefactory")"
else
  FACTORY_FOLDER="$demo_root/azurefactory"
fi
```

This folder is on the same computer as the demo API. A real operation uses
the actual folder on the computer running the API.

### 3. Read health and the factory list

```bash
curl --silent --show-error --fail-with-body --noproxy '*' \
  "$API_URL/health" || exit 1
printf '\n'

curl --silent --show-error --fail-with-body --noproxy '*' --get \
  "$API_URL/api/v1/factory-catalog" \
  --header "X-API-Key: $API_KEY" \
  --data-urlencode "folder=$FACTORY_FOLDER" || exit 1
printf '\n'
```

Expect a healthy service and an empty factory list. **You are finished.**
Stop the idle demo server with Ctrl+C in its terminal when done.

<details markdown="1">
<summary>More info</summary>

Interactive API help: `http://127.0.0.1:8876/docs`.
The exact HTTP definitions are at `/openapi.json`.
Curl sends HTTP requests; it is not the `azurefactory` CLI.
Do not send privileged requests from browser JavaScript with an API key.

</details>

</details>
<!-- /factory-tool -->

## Next: a real registered factory

Use [guide 19](19-cli-and-api-and-usage.md) or [guide 20](20-cli-and-api-and-usage.md)
with your real service address and private key. **Do not reuse the public demo
key or its empty folder.** The documentation site remembers the selected tool.

### The five steps

| Step | Meaning | Remember |
| --- | --- | --- |
| Check / preflight | Validates your configuration and environment. | Resolve any reported problems first. |
| Prepare | Shows changes for review. | No deployment yet. |
| Review and approve | Check the factory, environment and changes. | Approve only what you intend. |
| Confirm / start | For deployment, sends the approved configuration to the configured ADO/GHA pipeline and starts it. | A settings-only confirmation saves settings; it does not deploy. |
| Follow progress | Reads status and output from the current deployment run. | Check a missing response before trying again. |

### First identify which variables.json you mean

| File / location | Ownership and editing rule |
| --- | --- |
| Registered `azurefactory\factories\<key>\scalesets\<suffix>\projects\projectNNN\variables.json` | Written by the service. Use supported settings requests; manual changes are not automatically loaded and can be overwritten. |
| Registered `azurefactory\register.json`, bindings, receipts and encrypted profiles | Maintained by the service. Do not edit them to change factory identity, approve work or bypass errors. |

## If something goes wrong

| Problem | What to do |
| --- | --- |
| A variable or path is missing | Run the setup for your chosen tab in the same terminal/process as its requests. |
| Connection refused | Start the service and check the address/port. |
| Wrong key / 401 | Use the key belonging to that service. |
| Python cannot import the SDK | Check the source folder or selected Python environment. |
| Blocked operation / missing response | Read the message and check the existing run. Do not repeat a deployment or deletion blindly. |

<details markdown="1">
<summary>More info</summary>

### Setup and versions

Use compatible API and client versions. A published source update is not an
installed upgrade. The original parity baseline was API `d52463f` and accelerator
`eb077742`; named convenience helpers were added in `0da0d85b`. Environment-only
placement needs the newer API implementation; an older API may return 422.
Do not reset another person's checkout or change a deployment pin just to follow
a tutorial.

The API key does not grant Azure permissions. Settings saves, deployments and
deletions have separate approval steps. Keep keys and review files private.
API paths refer to the computer running the service.

### Support labels

| Label | Meaning |
| --- | --- |
| **implemented** | Available in the reviewed code; check the installed version. |
| **generic-access only** | Use a general request rather than a named shortcut. |
| **conditional/blocked** | Software, permissions, settings and deployment checks must pass. |
| **not implemented** | The complete behavior is not available. |

### Three-interface coverage

| Capability | REST | Python SDK | CLI | Important limit |
| --- | --- | --- | --- | --- |
| Health, schema, capabilities and account checks | implemented | implemented | implemented | `doctor` is an extra CLI helper. |
| Create factory configuration | implemented | implemented | implemented | Saves settings only. |
| Clone/add scale set/project/placement | implemented | implemented | implemented | Does not copy deployed resources or data. |
| Latest successful placement in a selected environment | implemented in newer API source | implemented | implemented | Successful recorded common deployment required; no implicit environment. |
| Read/replace registered settings | implemented | implemented | implemented | Review and save separately from deployment. |
| Parameter editing and override removal | implemented | implemented | implemented | Removing an override is not deleting a resource. |
| Remove never-deployed local drafts | implemented | implemented | implemented | Checked local removal only. |
| GitHub workflow status/watch | implemented | implemented | implemented | Not an ADO watcher. |
| Sample reports, saved results and costs | implemented | implemented | implemented | Actual billing requires Azure reads. |
| Deployment and registered bootstrap | conditional/blocked | conditional/blocked | conditional/blocked | Requires compatible setup and runtime. |
| Whole-factory deletion/status/recovery | conditional/blocked | conditional/blocked | conditional/blocked | Projects finish before common teardown. |
| Project/scale-set Azure deletion | conditional/blocked | implemented preparation | implemented preparation | Actual deletion still needs all ownership/retention checks. |
| Captured Dev-to-Stage-to-Prod promotion | not implemented as execution | not implemented as execution | not implemented as execution | Capturing/reviewing inputs is not target deployment. |

### The eight scenarios

| Scenario | Support and limit | Guide |
| --- | --- | --- |
| A. New factory, hub/VPN, project001 and environments | **implemented** configuration; **conditional/blocked** deployment. | 19 |
| B. Add an AI Factory scale set | **implemented** configuration; **conditional/blocked** deployment. Not VMSS. | 19 |
| C. Choose latest successful eligible scale set | **implemented** in an explicit environment on a compatible API. | 19 |
| E. Add/update/remove settings and resources | Settings are **implemented**; Azure changes are **conditional/blocked**. | 19/20 |
| G. Delete a project | Named preparation is **implemented**; execution is **conditional/blocked**. | 20 |
| H. Keep hub/VPN/dependencies during factory deletion | **conditional/blocked**; resources that must stay can block group deletion. | 20 |
| D. Promote captured configuration/version across environments | **not implemented** as a complete deployment operation. | 19 |
| F. Choose APIM versus Kong | Unified selection is **not implemented**; component support is **conditional/blocked**. | 19 |

### Optional developer regression tests

These are not needed to use any of the three tools. The offline consumer 114
harness checks the interfaces with simulated provider results; it makes no Azure
changes and does not need a running demo server. Its README contains the runner.
The earlier `25 passed, 1 warning` result was successful; the `httpx` deprecation
warning was not an instruction to install another dependency.

[Offline test instructions](https://github.com/jostrm/azure-enterprise-scale-byor-114).
Consumer 114 is not an Azure sandbox; consumer 113 is not used here.

### References

[CLI/SDK reference](../../../environment_setup/azurefactory-cli/readme.md),
[API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md),
[canonical API guide](https://github.com/jostrm/azure-aifactory-config/blob/main/docs/API.md).

</details>

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

## Choose how to author configuration: file-first or wrapper-first

The default registered-factory route uses commands/helpers (**wrapper-first**)
to save settings. You may write request JSON, but do not hand-edit registered
catalog files.

**File-first** applies to an exact consumer-owned `variables.json` used by a
supported older pipeline. Check the file, project and environment; keep a private
backup, edit only intended values, validate them, and separately review deployment.
Saving JSON does not publish provider variables, run pipelines or delete resources.

| File / location | Editing rule |
| --- | --- |
| Accelerator `environment_setup\aifactory\variables.json` | Shared defaults, not a customer-settings shortcut. |
| Legacy consumer `aifactory\variables.json` or selected project JSON | Manual editing may apply; confirm which file the pipeline actually reads. |
| `.env`, ADO `variables.yaml`, GitHub Environment variables | Separate inputs with explicit save/publish steps; no automatic synchronization. |

Legacy `config review/save` and `ConfigurationDraft` preserve persistent JSON.
Reload after manual changes; an old review is no longer valid. Migration to a
registered factory is a separate operation. Legacy `submitted` means the local
script exited zero, not that Azure succeeded.

Advanced CLI enrollment is a separate local implementation, not equivalent
REST/SDK provisioning. It can create resources and grant roles. See guide 19's
tool-specific alternatives and the canonical reference.

<details markdown="1">
<summary>More info</summary>

There is no two-way sync from arbitrary JSON edits into the register. Registered
project exports can be overwritten. Never reconstruct `_json_source` or change
review hashes to replay a stale save.

The pipeline JSON reader applies `dev`, then `stage_prod` for non-Dev, then exact
`test`/`prod` overrides when present. Registered snapshots use `dev` and
`stage_prod` with placement checks; these formats are not interchangeable.

[Legacy JSON editing](../../../environment_setup/azurefactory-cli/readme.md#edit-a-legacy-json-projects-configuration-without-deployment) |
[Pipeline reader](../../../environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py)

</details>

</details>
