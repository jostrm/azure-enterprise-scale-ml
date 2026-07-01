# AI model throttling via network rule (GenAI consumption cap)

Cap Azure AI Foundry / Cognitive Services **token consumption** by **cutting network access**
to the model endpoints when a **cost budget** or **token threshold** is exceeded — at either a
**subscription** or a single **project resource group** scope.

This is the "circuit breaker" pattern from `ignore.md`:

```
Azure Monitor / Consumption
     │   (cost budget alert  AND/OR  token scheduled-query alert)
     ▼
Action Group
     │   (logicAppReceiver)
     ▼
Logic App (Consumption, managed identity)
     │   reject private endpoints + disable public access
     ▼
Azure AI Foundry / Cognitive Services accounts in scope  →  callers blocked
```

> **What "blocked" looks like:** callers get a connection/auth failure (public: `403`
> `PublicNetworkAccessDisabled`; private endpoint: connection refused / DNS failure), which stops
> further token spend. A *true* `429 Too Many Requests` requires an API gateway (Azure API
> Management AI Gateway) in front of the model — see [When you need a real 429](#when-you-need-a-real-429).

Teams do **not** change anything in their Foundry instance — this is applied centrally.

---

## Contents

| Path | What it is |
|------|------------|
| `scripts/throttle-genai.ps1` | Manual apply/revert (PowerShell, cross-platform `pwsh`). |
| `scripts/throttle-genai.sh`  | Manual apply/revert (Bash, for pipelines). |
| `bicep/main.bicep`           | Automated chain: Logic App + Action Group + budget + token alert. |
| `bicep/main.bicepparam`      | Example parameters. |
| `bicep/modules/*`            | Logic App, action group, budgets, token alert, RBAC. |

---

## Two ways to use it

### 1. Manual on/off (scripts) — the fastest way to apply a cap

The script **enumerates** every `Microsoft.CognitiveServices/accounts` in scope (so it needs no
resource names), and handles **both** access paths, saving prior state in resource **tags** so the
revert is exact:

- **Public accounts** → `publicNetworkAccess=Disabled` + `networkAcls.defaultAction=Deny`
- **Private endpoint accounts** → every **Approved** private endpoint connection set to **Rejected**

```powershell
# Throttle one project resource group
./scripts/throttle-genai.ps1 -Action Throttle -Scope ResourceGroup -ResourceGroup <project-rg>

# Revert (exact restore from saved tags)
./scripts/throttle-genai.ps1 -Action Unthrottle -Scope ResourceGroup -ResourceGroup <project-rg>

# Throttle a whole subscription
./scripts/throttle-genai.ps1 -Action Throttle -Scope Subscription -SubscriptionId <sub-id>

# See current state (no changes)
./scripts/throttle-genai.ps1 -Action Status -Scope ResourceGroup -ResourceGroup <project-rg>

# Preview only
./scripts/throttle-genai.ps1 -Action Throttle -Scope ResourceGroup -ResourceGroup <project-rg> -DryRun
```

Bash equivalent:

```bash
./scripts/throttle-genai.sh --action throttle   --scope resourcegroup --resource-group <project-rg>
./scripts/throttle-genai.sh --action unthrottle --scope resourcegroup --resource-group <project-rg>
./scripts/throttle-genai.sh --action throttle   --scope subscription  --subscription <sub-id>
./scripts/throttle-genai.sh --action status     --scope resourcegroup --resource-group <project-rg>
```

Add `-IncludeSearch` / `--include-search` to also cut Azure AI Search public access.

### 2. Automated chain (Bicep) — fires the cap when over budget/tokens

Deploys a Logic App that runs the same "cut network access" logic, wired to a **cost budget**
and/or a **token scheduled-query alert**.

```bash
az deployment sub create \
  --location swedencentral \
  --template-file bicep/main.bicep \
  --parameters bicep/main.bicepparam
```

> The automated chain **applies** the cap. **Removing** it (e.g. at the start of a new billing
> month) is done with the scripts (`-Action Unthrottle`) or a scheduled pipeline that calls them.

---

## How to apply on a **Subscription** vs a **Resource Group**

Both the scripts and the Bicep take a `Scope` / `throttleScope`:

| Target | Scripts | Bicep |
|--------|---------|-------|
| **Whole subscription** | `-Scope Subscription -SubscriptionId <id>` | `throttleScope='Subscription'` |
| **One project RG** | `-Scope ResourceGroup -ResourceGroup <rg>` | `throttleScope='ResourceGroup'` + `targetResourceGroup=<rg>` |

- **Subscription scope**: the cost budget is subscription-wide; the Logic App enumerates every
  Cognitive Services account in the subscription. RBAC is granted at subscription scope.
- **Resource-group scope**: the cost budget is filtered to that RG; only accounts in that RG are
  throttled. RBAC is granted at that RG only (least privilege).

---

## `esml-aifactory-exists` — auto-name resolution

If you run inside an **AI Factory**, you don't need to type resource-group / vnet / DNS names —
they are **derived** from the AI Factory naming convention.

**Scripts** — pass `-EsmlAifactoryExists`/`--esml-aifactory-exists` with the AI Factory
`variables.yaml`:

```powershell
./scripts/throttle-genai.ps1 -Action Throttle -Scope ResourceGroup `
  -EsmlAifactoryExists -VarsFile <path>/variables.yaml -Env dev
```

```bash
./scripts/throttle-genai.sh --action throttle --scope resourcegroup \
  --esml-aifactory-exists --vars-file <path>/variables.yaml --env dev
```

Derived (same concat logic as `job-2-genai-services.yaml`):

| Value | Convention |
|-------|-----------|
| subscription | `<env>_sub_id` |
| project RG | `{admin_aifactoryPrefixRG}{projectPrefix}project{project_number_000}-{admin_locationSuffix}-{env}{admin_aifactorySuffixRG}{projectSuffix}` |
| vnet RG | `vnetResourceGroup_param` **or** `{admin_aifactoryPrefixRG}{vnetResourceGroupBase}-{admin_locationSuffix}-{env}{admin_aifactorySuffixRG}` |
| vnet name | `vnetNameFull_param` **or** `{vnetNameBase}-{admin_locationSuffix}-{env}{admin_commonResourceSuffix}` |
| private DNS RG | = vnet RG (AI Factory private DNS zones live there) |

Any value you pass explicitly on the CLI overrides the derived one.

**If AI Factory is *not* used** (`esml-aifactory-exists` **not** set), pass names explicitly:

```powershell
./scripts/throttle-genai.ps1 -Action Throttle -Scope ResourceGroup `
  -ResourceGroup my-genai-rg `
  -VnetName my-vnet -VnetResourceGroup my-net-rg `
  -PrivateDnsResourceGroup my-net-rg -StorageAccountName mystg
```

**Bicep** equivalent — set `esmlAifactoryExists=true` and the naming params (leave
`targetResourceGroup` empty):

```bicep
param esmlAifactoryExists = true
param env = 'dev'
param aifactoryPrefixRG = 'acme-1-'
param projectNumber = '001'
param locationSuffix = 'swc'
param aifactorySuffixRG = '-001'
// targetResourceGroup left empty -> derived to acme-1-project001-swc-dev-001
```

---

## Prerequisites

1. **Azure CLI** (`az`) logged in (`az login`) with rights to modify
   `Microsoft.CognitiveServices/accounts` and their `privateEndpointConnections` in the target
   scope. Bash script also needs **`jq`**.
2. **A management resource group** to host the **Logic App** and **Action Group** (Bicep only).
   Pass it as `throttleResourceGroup`; defaults to the target project RG.
3. **A Logic App (Consumption)** — created by the Bicep (`logicAppName`, selectable). This is the
   throttle executor. It is a **pre-req resource** in the sense that the automated chain provisions
   it; choose its name with the `logicAppName` parameter.
4. **Application Insights / Log Analytics** *(recommended pre-req for observability)* — pass its
   Log Analytics workspace id as `logAnalyticsWorkspaceResourceId` to capture Logic App run logs.
5. For the **token scheduled-query alert** *(optional)*: a **Log Analytics workspace** that
   receives the Foundry accounts' **platform metrics** (add a diagnostic setting on each account
   sending `AllMetrics`), so token metrics land in the `AzureMetrics` table.

---

## Permissions required on the Logic App managed identity (MI)

The Logic App uses a **system-assigned managed identity**. The Bicep grants it:

| Role | Scope | Why |
|------|-------|-----|
| **Cognitive Services Contributor** (`25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68`) | Subscription *or* target RG (matches `throttleScope`) | Read accounts, set `publicNetworkAccess` / `networkAcls`, and **approve/reject private endpoint connections**. |

This role is enough for the throttle actions (network settings + PE connection state). Least
privilege: for RG-scope throttling the assignment is on the RG only. For the manual scripts, the
**signed-in user** needs the equivalent rights (Cognitive Services Contributor, or Contributor).

> If you also enable the **cost budget**, budgets are created at subscription/RG scope by the
> deployment identity — the deploying principal needs `Microsoft.Consumption/budgets/write`
> (Contributor or Cost Management Contributor).

---

## Triggers (both supported)

| Trigger | Param | Detects | Notes |
|---------|-------|---------|-------|
| **Cost budget** | `enableBudget=true`, `budgetAmount`, `actualThresholdPercent`, `forecastThresholdPercent`, `budgetStartDate` | Actual/forecasted **cost** crossing % of the monthly amount | Real cost cap; currency-based. |
| **Token scheduled query** | `enableTokenAlert=true`, `workspaceResourceId`, `tokenThreshold` | Summed **tokens** over a rolling window (e.g. > 50M/month) | Requires Foundry metrics in Log Analytics. |

---

## Reverting / turning it off

- **Manual:** run the script with `-Action Unthrottle` — it restores the exact prior state from
  the tags it saved (`esmlThrottleState`, `esmlThrottlePrevPublicNet`, `esmlThrottlePrevDefaultAcl`,
  `esmlThrottledPeConns`) and re-approves only the PE connections it rejected.
- **Automated:** disable/delete the budget or scheduled-query alert to stop new throttling, then
  `-Action Unthrottle` to lift an active cap. A common pattern is a scheduled pipeline that calls
  `-Action Unthrottle` on the 1st of each month.

---

## When you need a real `429`

The network-rule approach **stops consumption** but returns connection/`403` errors, not `429`.
If callers must receive a graceful `429 Too Many Requests` (with retry semantics), put **Azure API
Management as an AI Gateway** in front of the models and use the **token-limit policy**. That is a
larger change (teams call the gateway instead of the account directly). This folder implements the
**central, no-team-change** network throttle from `ignore.md`; the two can be combined.

---

## Safety notes

- The scripts are **idempotent**: throttling an already-throttled account is skipped; unthrottling
  an account not throttled by this tool is skipped (it never touches PE connections it didn't
  reject).
- Use `-DryRun` / `--dry-run` first to preview.
- Rejecting a private endpoint connection is reversible via approve; disabling public access is
  reversible via the saved tag value.
