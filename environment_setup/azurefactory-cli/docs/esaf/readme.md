# ESAF: the Python SDK for the six AI Factory scenarios

`from azurefactory import esaf` runs each AI Factory lifecycle scenario with **one call**:

```python
from azurefactory import esaf

esaf.init_factory()                                      # 1 Init the AI Factory
esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16")   # 2 Add a scale set
esaf.upsert_project("002", "dev")                        # 3 Add or update a project
esaf.delete_project("002", "dev")                        # 4 Delete a project
esaf.delete_scale_set("002", "dev")                      # 5 Delete a scale set
esaf.delete_factory()                                    # 6 Delete the AI Factory
```

Each call is one request to the **Factory API** (`POST /api/v1/esaf/<scenario>`). The API runs the scenario as a
background job: it prepares every review, confirms it, waits for a busy lock, prepares again after a transient
refusal and retries a failed run. The call returns at once with an `EsafJob`, and `job.wait()` follows it to its end.

> [!WARNING]
> **Calling a scenario is the approval.** It changes Azure (it deploys or deletes), so call it only for what you
> mean to change. There is no separate confirm step.

This guide runs everything **locally**, on Windows, with the API on your own machine. The example paths are a working
local layout; replace them with your own folders.

> [!NOTE]
> New to ESAF? Start with the [quickstarts](../../../../documentation/v2/quickstarts/README.md). They start the
> Factory API from the app, so you don't need the API's source repository that step 1 below uses.

| What | Example path |
|---|---|
| Factory API source (repository `jostrm/azure-aifactory-config`) | `C:\work\factory-api` |
| Accelerator with the SDK (repository `jostrm/azure-enterprise-scale-ml`) | `C:\work\azure-enterprise-scale-ml` |
| Your consumer repository's `azurefactory` folder (the factory register) | `C:\work\team-factory\azurefactory` |

## 1. Start the Factory API

The API checkout must be on `main` (it has the `/api/v1/esaf` routes). From its folder:

```powershell
Set-Location C:\work\factory-api
git pull --ff-only
.\start-api.ps1
```

It prints, for example:

```text
Factory API 1.0.0 is ready at http://127.0.0.1:8765 (pid 58448).
API key: from the new file C:\Users\<you>\.aifactory\api.key
Logs: C:\Users\<you>\AppData\Local\Temp\aifactory-api\api-8765.log and ...\api-8765.err.log
```

`start-api.ps1` starts the API hidden on `127.0.0.1`, waits until `/health` answers and never prints the key.

| Option | Default | Meaning |
|---|---|---|
| `-Port` | `8765` | The port to listen on. |
| `-Restart` | off | Replace a Factory API already listening on that port (after `git pull`, to load new code). |
| `-ApiKeyFile` | `%USERPROFILE%\.aifactory\api.key` | The key file; created with a new random key when missing. `AIFACTORY_API_KEY`, when set, wins. |
| `-AcceleratorRoot` | not set | The accelerator checkout the API deploys from, for example `..\azure-enterprise-scale-ml`. |
| `-Python` | `.venv\Scripts\python.exe` in the API folder, else `python` | The interpreter. |
| `-DryRun` | off | Print what it would start, without starting it. |

Check that the running API has the ESAF routes. It must list seven:

```powershell
(Invoke-RestMethod http://127.0.0.1:8765/openapi.json).paths.PSObject.Properties.Name | Select-String esaf
```

> [!NOTE]
> First time only, in the API folder: `python -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
> An API that is already running keeps its old code: after a `git pull`, run `.\start-api.ps1 -Restart`.

## 2. Install the SDK

The SDK needs Python 3.10 or later and has no third-party dependencies. Install it from the accelerator checkout, on
`main`; `-e` makes a later `git pull` take effect without reinstalling:

```powershell
git -C C:\work\azure-enterprise-scale-ml pull --ff-only
python -m pip install -e C:\work\azure-enterprise-scale-ml\environment_setup\azurefactory-cli
python -c "from azurefactory import esaf; print(esaf.__all__)"
```

## 3. Connect once

Every call uses one connection, so the calls name only what they change. Set it in the terminal you run Python from:

```powershell
$env:AIFACTORY_API_URL = 'http://127.0.0.1:8765'
$env:AIFACTORY_API_KEY = (Get-Content -Raw "$env:USERPROFILE\.aifactory\api.key").Trim()
$env:ESAF_FOLDER = (Resolve-Path 'C:\work\team-factory\azurefactory').Path
```

| Variable | Required | Meaning |
|---|---|---|
| `ESAF_FOLDER` | yes | The absolute path of the `azurefactory` folder **on the API host** (here, the same machine). |
| `AIFACTORY_API_URL` | no | The API address; default `http://127.0.0.1:8765`. |
| `AIFACTORY_API_KEY` | yes | The API key. Read it from the key file; never put it in a script, URL or log. |
| `ESAF_TIMEOUT` | no | Seconds one HTTP request may take; default `1800`. |

Or connect in code instead of with variables. `connect()` returns the session every later call uses:

```python
from azurefactory import esaf

esaf.connect(folder=r"C:\work\team-factory\azurefactory",
             url="http://127.0.0.1:8765", factory="acme-ai")   # api_key= too, or AIFACTORY_API_KEY
```

| `connect()` parameter | Meaning |
|---|---|
| `folder` | The `azurefactory` folder; default `ESAF_FOLDER`. |
| `url` | The API address; default `AIFACTORY_API_URL`, else `http://127.0.0.1:8765`. |
| `api_key` | The API key; default `AIFACTORY_API_KEY`. |
| `factory` | Factory key or id. Only needed when the folder holds more than one factory. |
| `client` | Your own `AzureFactoryClient`, for example with another timeout. |

Check the connection with a read that changes nothing. It lists the folder's factories (`[]` for a new folder):

```powershell
python -c "from azurefactory import esaf; s = esaf.connect(); print([f['key'] for f in s.client.catalog_list(s.folder)['factories']])"
```

## 4. The six scenario methods

`environment` is `"dev"`, `"stage"` or `"prod"`. It is **required** on scale-set and project calls: the same suffix or
project number can exist in several environments, and a delete never reaches another environment. Numbers are three
digits, as strings: `"002"`.

Every method also accepts these keyword arguments:

| Keyword | Default | Meaning |
|---|---|---|
| `wait` | `False` | `True` waits until the job ends and puts its final state in `job.result`. |
| `poll` | `1` | Seconds between job reads while waiting. |
| `retries` | server default `2` | How often the API runs the scenario again after a failed run (0-5). |
| `version_ref` | the factory's version | An explicit accelerator version or branch to deploy. |
| `session` | the `connect()` session | An explicit `esaf.Session(folder, client, factory)`, for code that serves several folders. |

### 1. `esaf.init_factory()`: Init the AI Factory

```python
esaf.init_factory(*, creation_request=None)
```

| Parameter | Meaning |
|---|---|
| (none) | Submits the folder's **saved factory draft** (for example saved in the Config Wizard) as one approved workflow. |
| `creation_request` | Saves a new factory and starts it in the same call. The body is the creation API's full-bootstrap request: `{"contract_version": 1, "mode": "full-bootstrap", "action": "create-factory", "folder": ..., "orchestrator": "gha", "config": {...}, "factory_key": ..., "region_short_name": ...}`. `config` needs at least `factory_prefix`, `location` and `scale_set_number`. |

It deploys the common Dev resource group, its network and the initial project001. About one hour.

### 2. `esaf.add_scale_set(scale_set, environment)`: Add a scale set

```python
esaf.add_scale_set(scale_set, environment, *, cidr=None, max_projects=None, subscription_id=None,
                   tenant_id=None, orchestrator=None, settings=None)
```

| Parameter | Meaning |
|---|---|
| `scale_set` | The suffix, for example `"002"`. One environment can hold several scale sets. |
| `environment` | `"dev"`, `"stage"` or `"prod"`. |
| `cidr` | The new scale set's **VNet range**, for example `"10.141.0.0/16"`. Required for a new scale set; the deployment pipeline computes its subnets (with BYOSubnet they already exist). It must not overlap the hub or any peered VNet. |
| `max_projects` | Project capacity; default `7`. |
| `subscription_id`, `tenant_id`, `orchestrator` | Default to the environment's existing scale set; `orchestrator` is `"gha"` or `"ado"`. |
| `settings` | Optional flat wizard settings saved at scale-set scope before deployment, such as `BYO_subnets`, `vnetResourceGroup_param`, `vnetNameFull_param`, `byoASEv3` or `byoAseFullResourceId`. |

It registers the scale set (if new), extends the factory's single writer to it and deploys its common part. Calling
it again for an existing scale set resumes: registration is skipped. About 15-30 minutes.

### 3. `esaf.upsert_project(project, environment)`: Add or update a project

```python
esaf.upsert_project(project, environment, *, scale_set=None, settings=None, display_name=None)
```

| Parameter | Meaning |
|---|---|
| `project` | The project number, for example `"002"`. |
| `environment` | `"dev"`, `"stage"` or `"prod"`. |
| `scale_set` | Which scale set to place it on. Needed only when the environment has more than one. |
| `settings` | Project settings to change, for example `{"tag_costcenter": "lab"}`; omitted keys keep their value. |
| `display_name` | A display name for a new project. |

A new project is registered and deployed; an existing one gets its settings saved and is redeployed. It is the same
call either way ("upsert"). `esaf.apply_project` is an alias. About 25-30 minutes.

### 4. `esaf.delete_project(project, environment)`: Delete a project

```python
esaf.delete_project(project, environment, *, scale_set=None, include_project_subnets=None,
                    include_keyvault_and_resource_group=None)
```

| Parameter | Default | Meaning |
|---|---|---|
| `project`, `environment` | | Which project, in which environment. |
| `scale_set` | | Needed only when the project is on more than one scale set in that environment. |
| `include_project_subnets` | `False` | Also delete the project's subnets. |
| `include_keyvault_and_resource_group` | `True` | `False` deletes only the project's services and keeps its Key Vault and resource group. |

The API grants the factory's deletion permission first (once), then runs the project pipeline with the deletion flags.

### 5. `esaf.delete_scale_set(scale_set, environment)`: Delete a scale set

```python
esaf.delete_scale_set(scale_set, environment)
```

Deletes the scale set's registered resources in that environment. Other scale sets stay.

### 6. `esaf.delete_factory()`: Delete the AI Factory

```python
esaf.delete_factory()
```

Deletes every registered resource group of the factory and removes its local configuration. Shared hubs,
subscriptions, Entra groups and Git history stay.

## 5. Follow a job

Each method returns an `EsafJob`:

```python
job = esaf.upsert_project("002", "dev", scale_set="001")
print(job.id)              # persist this to follow the job later
state = job.status()       # one read
state = job.wait()         # reads every second until the job ends; wait(timeout=8 * 3600, poll=1)
print(state["status"], "-", state["message"])
```

A job read later, for example from another script after a restart:

```python
from azurefactory import esaf

job = esaf.EsafJob("upsert_project", "esaf", "0b7d6c84-3a52-4f05-9a27-52a1c3f8e0d1", esaf.connect())
print(job.status()["status"])
```

| Job field | Meaning |
|---|---|
| `status` | `accepted`, `preparing`, `confirming`, `running`, `retrying` (still going), or `succeeded`, `failed`, `blocked`, `interrupted` (ended). |
| `message` | What happened, in one line. |
| `child` | The run the scenario started: `{"kind": "catalog" \| "factory-deletion" \| "workflow", "id", "status"}`. |
| `attempt`, `attempts` | Which run this is, and every earlier run with its outcome. |
| `events` | The API's notes: lock waits, re-prepares, released claims. |
| `blockers`, `problem` | Why a `blocked` or `failed` job stopped, with the server's own reason. |

`interrupted` means the API stopped before the scenario started its run: submit the call again.

## 6. Errors

A refusal raises before anything is started:

| Exception | When |
|---|---|
| `TypeError` | `environment` is missing from a scale-set or project call. |
| `ConfigError` | Unknown or ambiguous target (for example `scale_set` needed), a new scale set without `cidr`, an invalid `environment`, no `ESAF_FOLDER`, or an API without the ESAF routes. |
| `BlockedError` | The server's review refused it (its blockers are in `error.details["blockers"]`), or another ESAF job is still running on the factory. |
| `AuthError` | Missing or wrong API key, or the API is not on the same machine (the routes accept loopback only). |
| `FailureError` | The API failed or its storage is unavailable. |

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

Calling the same scenario for the same target while its job still runs returns that job instead of starting a second
one. A different scenario on the same factory waits: it raises `BlockedError` until the running job ends.

## 7. A complete script: Scenarios 1-3

Save as `scenarios_1_3.py` and run it in the terminal where you connected (step 3). It builds a Dev AI Factory, adds
scale set DEV/002, then adds project 002 on DEV/001 and updates it. Expect about two hours.

```python
import json
from azurefactory import esaf


def run(label, job):
    print(label, "ESAF job", job.id)
    state = job.wait()
    print(label, state["status"], "-", state["message"])
    if state["status"] != "succeeded":
        raise SystemExit(f"{label} stopped: {state.get('blockers') or state.get('problem')}")


config = json.load(open(r"C:\work\team-factory\bootstrap-config.json", encoding="utf-8-sig"))
creation = {"contract_version": 1, "mode": "full-bootstrap", "action": "create-factory",
            "folder": r"C:\work\team-factory\azurefactory",
            "orchestrator": "gha", "config": config, "factory_key": "acme-ai", "region_short_name": "sdc"}

run("Scenario 1", esaf.init_factory(creation_request=creation))
run("Scenario 2", esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16"))
run("Scenario 3", esaf.upsert_project("002", "dev", scale_set="001"))
run("Scenario 3 update", esaf.upsert_project("002", "dev", scale_set="001",
                                             settings={"tag_costcenter": "tutorial-lab"}))
```

`bootstrap-config.json` is the factory's bootstrap configuration: subscription, tenant, region, prefix, network and
hub settings. The TutorialApp lesson `esaif-python-sdk-esaf-01`, Task 1.1, writes it for you. Scenarios 4-6 are the
same pattern in reverse: `delete_project("002", "dev")`, `delete_scale_set("002", "dev")`, `delete_factory()`.

## 8. The same scenarios from the command line

The `azurefactory` CLI installed with the SDK has the same six commands. It prints the job id, or with `--wait` the
final job:

```powershell
azurefactory esaf init-factory --wait
azurefactory esaf add-scale-set 002 dev --cidr 10.141.0.0/16 --wait
azurefactory esaf upsert-project 002 dev --scale-set 001 --wait
azurefactory esaf delete-project 002 dev --wait
azurefactory esaf delete-scale-set 002 dev --wait
azurefactory esaf delete-factory --wait
azurefactory esaf job 0b7d6c84-3a52-4f05-9a27-52a1c3f8e0d1 --wait
```

`--folder` overrides `ESAF_FOLDER`, `--factory` selects a factory, and `--retries` and `--version-ref` work as in
Python. The exit code is `0` when the job succeeded or is still running, `3` when it was blocked and `5` when it failed.

## 9. Troubleshooting

| Message | Fix |
|---|---|
| `Select an absolute local factory folder without traversal.` | `ESAF_FOLDER` is not an absolute path. Check it with `$env:ESAF_FOLDER` and set it with `Resolve-Path` (step 3). |
| `Select the existing aifactory or azurefactory folder.` | The folder does not exist, or is not named `azurefactory`. |
| `AIFACTORY_API_KEY is required` or HTTP 401 | The terminal has no key, or an old one: `start-api.ps1` may have created a new key file. Read it again (step 3). |
| `The Factory API has no /api/v1/esaf routes` | The API runs older code. `git pull` in the API folder, then `.\start-api.ps1 -Restart`. |
| `Port 8765 is already in use` | Another API is running: `.\start-api.ps1 -Restart` replaces it. |
| `ModuleNotFoundError: azurefactory` | The SDK is not installed in that Python: run step 2 with the same `python`. |
| `More than one dev scale set matches; pass scale_set.` | Name the scale set: `scale_set="001"`. |
| A job stays `blocked` | Read `job.status()["problem"]` and `["blockers"]`, fix what they name, and call the scenario again: steps that are already done are skipped. |

## More

- The API routes, request bodies and job fields: [Factory API guide, ESAF section](https://github.com/jostrm/azure-aifactory-config/blob/main/docs/API.md).
- The SDK source: [esaf.py](../../src/azurefactory/esaf.py). The whole SDK and CLI: [readme](../../readme.md).
- The C# equivalent for the MAUI apps: `Esaf` in `ESAIF.DomainLayer` (`InitFactoryAsync`, `AddScaleSetAsync`, ...).
- A guided, checked walkthrough of Scenarios 1-3: the TutorialApp lesson `esaif-python-sdk-esaf-01`.
