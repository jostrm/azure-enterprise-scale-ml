# 22) AI Factory lifecycle Azure Function (CoreTeam)

A private Azure Function that runs the AI Factory lifecycle as an API: initialize a factory, add a scale set, add or
update a project, and delete a project, a scale set or a whole factory. Each change is a review followed by a separate
confirmation, and the Function follows the resulting GitHub workflow runs until they succeed or fail.

Template: [usecase_code/10-azure-function/12_func_aifactory_lifecycle](../../../usecase_code/10-azure-function/12_func_aifactory_lifecycle/README.md).
Design and constraints: [Lifecycle Function](../../architecture/contracts/Lifecycle-Function.md).

## When to use it

- You want one API (or a portal, agent or pipeline on top of it) for factory lifecycle, instead of the wizards or CLI.
- You want lifecycle runs observed through GitHub `workflow_run` events, with a poller as a fallback.

It does not replace the Factory API: it calls it through REST or the `azurefactory` SDK. Because the API serves catalog
and deployment routes to loopback clients only, real calls run on a management runner next to the API.

## Readable IDs

| Scenario | Route | Body |
|---|---|---|
| 1 Init factory | `POST /api/v1/lifecycle/init-factory/prepare` | `{"factoryId": "aif-121-sdc-dev"}` |
| 2 Add scale set | `POST /api/v1/lifecycle/add-scaleset/prepare` | `{"scalesetId": "aif-121-sdc-dev-002"}` |
| 3 Add or update project | `POST /api/v1/lifecycle/add-or-update-project/prepare` | `{"projectId": "aif-121-esml-project002-sdc-dev-001-rg"}` |
| 4 Delete project | `POST /api/v1/lifecycle/delete-project/prepare` | `{"projectId": "..."}` |
| 5 Delete scale set | `POST /api/v1/lifecycle/delete-scaleset/prepare` | `{"scalesetId": "..."}` |
| 6 Delete factory | `POST /api/v1/lifecycle/delete-factory/prepare` | `{"factoryId": "..."}` (single-environment factories) |

A ProjectId is the project's resource group name. Azure names use `dev`, `test` and `prod`.

## Review and confirm

```powershell
$base = 'https://<function app>.azurewebsites.net/api'
$headers = @{ 'x-functions-key' = $functionKey }
$op = Invoke-RestMethod -Method Post -Uri "$base/v1/lifecycle/add-scaleset/prepare" -Headers $headers `
  -Body (@{ scalesetId = 'aif-121-sdc-dev-002' } | ConvertTo-Json) -ContentType 'application/json'
$step = $op.steps[$op.currentStep]
$step.preview                      # plan, affected resource groups, blockers, canExecute, expiresAt
Invoke-RestMethod -Method Post -Uri "$base/v1/operations/$($op.operationId)/confirm" -Headers $headers `
  -Body (@{ confirmationToken = $step.preview.confirmationToken } | ConvertTo-Json) -ContentType 'application/json'
Invoke-RestMethod -Uri "$base/v1/operations/$($op.operationId)" -Headers $headers   # status, runs, history
```

Deletes also need `confirmationPhrase` (shown in the preview, for example `DELETE aif-121-sdc-dev-002`). A review
expires after `AIF_REVIEW_TTL_SECONDS` (410 after that). Errors are `application/problem+json` with a stable `code`.

## Set it up in a project

1. Copy the template to your consumer repo (`aifactory-usecase-code/10-azure-function/12_func_aifactory_lifecycle/`)
   and the workflows from its `workflows/` folder to `.github/workflows/` of the factory repo.
2. Create `settings.<consumer>.json` from `settings.example.json`: the project's VNet integration and private endpoint
   subnets, storage account, Application Insights, Log Analytics and Key Vault. Name the app outside purple's
   `func-prj<NNN>-` pattern, for example `aiflc-prj001-sdc-dev-<uniq>-001`.
3. Over the factory VPN, in PowerShell 7: `.\deploy.ps1 -SettingsFile .\settings.<consumer>.json -WhatIf`, then
   without `-WhatIf`. It creates a private B1 Linux plan and app (no public access, no basic publishing credentials)
   and deploys the code with a remote build.
4. Put the event secret and the GitHub token in the project Key Vault and set `AIF_KEY_VAULT_NAME`,
   `AIF_EVENT_SECRET_NAME` and `AIF_GITHUB_TOKEN_NAME`. Use a fine-grained token limited to the factory repo's Actions.
5. For events, register the management runner for the factory repo with its own label (for example
   `aif-lifecycle-mgmt`) and set the relay's `AIF_LIFECYCLE_EVENTS_URL` variable and `AIF_LIFECYCLE_EVENT_SECRET` secret.

Start with `AIF_BACKEND=mock` and `AIF_EXECUTOR=inprocess`, then `github-dummy`, before switching to the real API.
Add App Service authentication with an Entra app role before real deployments; function keys are for the mock passes.

## Limits

- Scenario 6 uses `delete-aifactory`, which deletes every environment of a factory. Multi-environment factories get
  409 `scope-not-supported`; delete their scale sets with scenario 5.
- Whole-factory deletion also removes a factory-owned access hub inside its own common resource group.
- The management runner must sit outside every factory the Function can create or delete; protect its scale set with
  `AIF_PROTECTED_IDS`.
