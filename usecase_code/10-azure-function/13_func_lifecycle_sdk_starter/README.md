# Lifecycle Function starter: your own Function on the azurefactory SDK, mock first

A small Azure Functions app (Python v2 model) to build your own lifecycle Function from. It runs scenario 3 (add or
update a project) as two reviewed steps against a **mock of the `azurefactory` SDK**, and switches to the real Factory
API with one setting. The full template with all six scenarios, GitHub run tracking, stores and the Azure deployment is
the sibling [12_func_aifactory_lifecycle](../12_func_aifactory_lifecycle/README.md).

## The idea: mock the SDK, not the Function

`MockFactoryClient` has the same method names, arguments and reply shapes as `azurefactory.AzureFactoryClient`, and
the rest of the code calls only those methods. Moving to the real API replaces one object:

```
HTTP (function_app.py, thin)  ->  lifecycle.py (two-step operations)  ->  client
                                                                         |- MockFactoryClient    (AIF_BACKEND=mock)
                                                                         '- AzureFactoryClient   (AIF_BACKEND=sdk)
```

| File | What it does |
|---|---|
| `factory_client.py` | `MockFactoryClient`: an in-memory Factory API with one factory (`aif-130-`, sdc, dev/001 with project001) and the SDK's methods `health`, `catalog_list`, `project_add_prepare`, `catalog_settings_prepare`, `catalog_prepare`, `catalog_confirm`, `catalog_job`. `make_client()` picks the mock or the real client from `AIF_BACKEND`. |
| `lifecycle.py` | Two steps per operation (configure, deploy-project). `prepare` resolves the ProjectId (the project resource group name) in `catalog_list` and returns the first review; `confirm` checks the token and expiry, saves the step as `confirming` and sends `catalog_confirm` **once** (a failed confirm is never retried); reading the operation polls `catalog_job` while the deployment runs. |
| `function_app.py` | `GET /api/v1/health` (anonymous), `POST /api/v1/lifecycle/{scenario}/prepare`, `GET /api/v1/operations`, `GET /api/v1/operations/{id}`, `POST /api/v1/operations/{id}/confirm` (function key). Errors are problem documents with a stable `code`. |
| `tests/test_lifecycle.py` | Add and update on the mock, a wrong token (400), bad IDs (400/404), an expired review (410), the routes, and the same code through the real SDK against the sibling's fake Factory API. |

The HTTP contract is the sibling's, so `aif_func.py` and the ESAIF TutorialApp tutorial `esaif-azure-function-01`
(in `jostrm/maui-apps`) work against it unchanged; there only Setup and Scenario 3 pass.

## Run it locally (mock)

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q tests            # 9 passed (the SDK test uses ..\12_func_aifactory_lifecycle\tests)
Copy-Item local.settings.example.json local.settings.json   # git-ignored
azurite --location $env:TEMP\azurite --silent
func start --enableAuth --port 7072                  # without --enableAuth, Core Tools never checks the key
```

`--enableAuth` makes the local host check function keys; they are kept in Azurite (container
`azure-webjobs-secrets`). Check that the key gets 200 and a wrong key gets 401 before you rely on it. Then, with
`aif_func.py` from the tutorial:

```powershell
$env:AIF_FUNC_URL = 'http://localhost:7072/api'; $env:AIF_FUNC_KEY = (Get-Content -Raw '<private folder>\func.key').Trim()
python aif_func.py health
python aif_func.py prepare add-or-update-project aif-130-esml-project002-sdc-dev-001-rg
python aif_func.py confirm      # configure: add project 002 to the catalog (configuration only)
python aif_func.py confirm      # deploy-project: the project's resource group
python aif_func.py wait         # succeeded
python aif_func.py prepare add-or-update-project aif-130-esml-project002-sdc-dev-001-rg enableAISearch=true
```

## Add the other scenarios

For each one: add the SDK methods it needs to `MockFactoryClient` with the SDK's exact signature
(`environment_setup/azurefactory-cli/src/azurefactory/client.py`), write a test, then add its steps to `lifecycle.py`.
These are the calls the sibling makes (`aif_lifecycle/adapters/sdk_backend.py`, `factory_api.py`):

| Scenario | Steps | SDK calls |
|---|---|---|
| 1 `init-factory` | configure, bootstrap | `creation_prepare(body)` → `creation_confirm(folder, confirmation_id)`; `creation_workflow_prepare(body)` → `creation_workflow_start(folder, workflow_id, confirmation_id, authorization_hash=)` → `creation_workflow_status(folder, workflow_id)` |
| 2 `add-scaleset` | configure, add-project001, enroll-scaleset, deploy-common, deploy-project001 | `scaleset_add_prepare(folder, factory_id, scale_sets, expected_revision=)`; `project_add_prepare(...)`; `enroll_scale_set_prepare(body)` → `enroll_scale_set_confirm(folder=, confirmation_id=, preview_hash=, confirmation_phrase=)`; `catalog_prepare(deploy body)` → `catalog_confirm` → `catalog_job` |
| 3 `add-or-update-project` | configure, deploy-project | **this starter** |
| 4 `delete-project` | delete-project | `project_delete_prepare(folder, factory_id, project_id, environments=, include_project_subnets=, include_keyvault_and_resource_group=, expected_revision=, scale_set_id=)` → `catalog_confirm` → `catalog_job` |
| 5 `delete-scaleset` | delete-scaleset | `scaleset_delete_prepare(folder, factory_id, scale_set_id, expected_revision=)` → `catalog_confirm` → `catalog_job` |
| 6 `delete-factory` | delete-factory | `delete_aifactory_prepare(body)` → `delete_aifactory_confirm(folder=, confirmation_id=, preview_hash=, confirmation_phrase=)` |

Keep the sibling's rules: one confirm per step and never a retry (a timeout is an unknown outcome to reconcile);
deletes need a typed phrase (`DELETE <target>` when the API gives none) and leave the catalog only after the run
succeeded; refuse real deletes unless a setting allows them (403 `deletes-disabled`); refuse targets that contain the
Function's own project.

## Switch to the real Factory API

1. **Prove the swap offline:** `pytest` already runs this code through the real `AzureFactoryClient` against the
   sibling's fake Factory API (`test_the_same_code_runs_on_the_real_sdk`).
2. **Run it on the API host.** The Factory API serves catalog and deployment routes to loopback clients only, so
   this Function must run next to it (`func start` on the same machine). For a Function in Azure, use the sibling's
   `AIF_EXECUTOR=github-runner`, where the management runner on the API host makes the calls.
3. **Settings** (`local.settings.json`; in Azure, read the key from Key Vault, never as a plain value):
   `AIF_BACKEND=sdk`, `AIF_FACTORY_API_URL=http://127.0.0.1:8765`, `AIF_FACTORY_FOLDER` (the consumer repo's
   `azurefactory` folder on the API host) and `AIF_FACTORY_API_KEY`.
4. **Read-only first:** `health`, then one `prepare` and read the review; nothing changes until you confirm. Then one
   real scenario 3 on a test project number. A real deploy review can take more than 10 minutes, so raise
   `AIF_FACTORY_API_TIMEOUT_SECONDS`, and mind the Function's `functionTimeout` (10 minutes in `host.json`).

Against the real API, scenario 1 also needs `wholeWorkflow: true` and `bootstrapConfig` in the prepare body, and
scenario 2 needs `scaleSet` (see the sibling's [README_More_Info.md](../12_func_aifactory_lifecycle/README_More_Info.md)).

## Limits of the starter

- One scenario (3). Operations live in memory: one instance only; use a durable store (Azure Table storage) before
  scaling out, as the sibling does with `AIF_STORE=table`.
- No GitHub event tracking, timer reconcile, Entra app role or deployment template: take those from the sibling.
