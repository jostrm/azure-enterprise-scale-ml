# Enterprise Scale AI Factory — GenAI consumption throttling (LLM cost circuit breaker)

**Turn-key, consumption-based throttling for LLM / GenAI models.** Set a **budget threshold** and
have Azure AI Foundry / Cognitive Services **automatically stopped** the moment spend or token
usage crosses the line — no code changes for the teams using the models.

Throttle at any level of the **Enterprise Scale AI Factory**:

- **AI Factory global level** — a budget across a whole **AI Factory project subscription**.
- **AI Factory project team level** — a budget scoped to a single **project resource group**.
- **Per environment** — different budgets for **dev / stage / production** of the same project.

| Who | Role in this feature |
|-----|----------------------|
| **AI Factory core team** | Owns the **AI Factory management subscription** and this governance tooling. Sets budgets and operates the throttle centrally. |
| **AI Factory project team** | The teams **being throttled**. They run their models in an **AI Factory project subscription / resource group** and change **nothing** — the cap is applied for them. |

This is an Enterprise Scale AI Factory feature: the **core team** governs cost centrally from the
**management subscription**, while **project teams** keep building. When a project (or a whole
AI Factory environment) exceeds its budget, its models are cut off until the cap is lifted (e.g. at
the start of the next billing month).

---

## Why this approach

- **Works for teams using Foundry directly** — existing Foundry model deployments, **no AI Gateway**
  in front. The models are called directly and this still caps them.
- **Works for teams using an AI Gateway in front of Foundry** — same central throttle applies to the
  underlying Foundry accounts regardless of what sits in front.
- **No changes for the project teams.** Unlike introducing an AI Gateway — where each backend model
  deployment must be re-provisioned as a gateway backend **and** the use-case solution must be
  changed to call the gateway instead of the direct Foundry endpoint — this feature requires the
  project team to change **nothing**. It is applied centrally by the core team.
- **Real-time, consumption-based.** It reacts to your **actual Azure consumption / cost** in
  real time — something **Azure Policy cannot do** (Policy governs configuration, not live spend).
- **Blocks on over-consumption at your threshold**, using **real data from your Azure consumption**
  (and your EA/negotiated pricing), not an estimate.
- **Works for all models.** No need to count tokens per model or convert token counts into cost
  (with EA discounts, per-model rates, etc.) — it reads the **billed consumption** directly.

## Features

- **Reversible** — turn it **ON** or **OFF**. State is saved so the revert is exact.
- **Networking mode** — works whether the accounts use **private endpoints only**, or **ACLs with
  public network access** (it handles both paths).
- **Scope** — apply at **resource group** level (project team) or whole **subscription** level
  (AI Factory global / per environment).
- **Trigger executor** — a **Logic App** with a **managed identity** performs the throttle when the
  consumption trigger fires.
- **Trigger-cap (consumption metric)** — the consumption trigger can fire on **Azure consumption
  (cost budget)** *and/or* on **Application Insights / Log Analytics** logs (token metrics).

---

## How it works — the "circuit breaker" pattern

Cap Azure AI Foundry / Cognitive Services **token consumption** by **cutting network access** to
the model endpoints when a **cost budget** or **token threshold** is exceeded — at either an
**AI Factory project subscription** or a single **project resource group** scope.

```
 AI Factory PROJECT subscription / resource group   AI Factory MANAGEMENT subscription / RG
 (project team's workload being throttled)          (core team's governance tooling)
 ┌─────────────────────────────────────┐       ┌────────────────────────────────────────┐
 │ Azure Monitor / Consumption          │       │                                        │
 │   (cost budget AND/OR token alert)   │──────▶│  Action Group  (logicAppReceiver)      │
 │                                      │       │        │                               │
 │ Cognitive Services / Foundry accounts│◀──────│        ▼                               │
 │   ← public access disabled           │  cross│  Logic App (Consumption, managed id)   │
 │   ← private endpoints rejected       │  -sub │   reject PEs + disable public access   │
 └─────────────────────────────────────┘       └────────────────────────────────────────┘
```

The **Logic App + Action Group** (the throttle executor) live in the **AI Factory management
subscription** — the core team's central subscription — separate from the **AI Factory project
subscription** being throttled. In a single-subscription AI Factory (e.g. a demo) the subscription
is the same, but the management **resource group** is always separate (it is never throttled).

> **What "blocked" looks like:** callers get a connection/auth failure (public: `403`
> `PublicNetworkAccessDisabled`; private endpoint: connection refused / DNS failure), which stops
> further token spend. A *true* `429 Too Many Requests` requires an API gateway (Azure API
> Management AI Gateway) in front of the model — see [When you need a real 429](#when-you-need-a-real-429).

**AI Factory project teams do not change anything** in their Foundry instance — the cap is applied
centrally by the **AI Factory core team**.

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

> **Scripts vs. Bicep — who touches what**
>
> - The **scripts act directly** on the **target** subscription/RG via `az` CLI. They **do not**
>   use a Logic App, an Action Group, or a management subscription — so they take **only the
>   target** (`-SubscriptionId` / `-ResourceGroup`). That is why you see just one resource group:
>   it is the **target RG** to throttle.
> - The **Bicep chain** is what introduces the **Logic App + Action Group** (in the *management*
>   subscription/RG) so throttling fires **automatically** when a budget/token threshold trips.
>   Only the Bicep path takes `managementSubscriptionId` / `managementResourceGroup` /
>   `logicAppName`.

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
# Run the deployment against the TARGET (throttled) subscription.
az account set --subscription <target-sub-id>
az deployment sub create \
  --location swedencentral \
  --template-file bicep/main.bicep \
  --parameters bicep/main.bicepparam
```

> The deployment runs at **subscription scope against the target subscription**. Budget + RBAC are
> created in the target; the Logic App + Action Group are deployed **cross-subscription** into the
> management subscription/RG (`managementSubscriptionId` / `managementResourceGroup`). The Logic
> App's managed identity is granted **Cognitive Services Contributor** on the target, so its
> cross-subscription ARM calls succeed at runtime.

> The automated chain **applies** the cap. **Removing** it (e.g. at the start of a new billing
> month) is done with the scripts (`-Action Unthrottle`) or a scheduled pipeline that calls them.

---

## Where the Logic App lives — the AI Factory management subscription (Bicep only)

The Logic App + Action Group are the **AI Factory core team's** governance tooling. The
**AI Factory management subscription** is a central subscription that holds tools for **governance
and management** used by the core team to manage the other **AI Factory project subscriptions**
connected to the AI Factory (and other AI Factory scalesets). The throttle executor lives there,
**separate** from the project workloads it throttles.

The Bicep therefore has **two pairs** of scope parameters:

| Side | Params | Meaning |
|------|--------|---------|
| **AI Factory project** (throttled) | `targetSubscriptionId` (empty = the deployment subscription), `targetResourceGroup` | The project team's workload to cap. Budget + RBAC land here. |
| **AI Factory management** (executor) | `managementSubscriptionId` (empty = same as project sub), `managementResourceGroup` (**required, must differ**), `logicAppName` | Hosts the Logic App + Action Group. Deployed cross-subscription by the core team. |

**Choosing the Logic App name:** set `logicAppName` (leave empty to auto-name `<namePrefix>-logic`).
This is the throttle executor the Bicep provisions in the management RG.

### If you use the Enterprise Scale Accelerator

The management subscription and its RG are known — set `managementSubscriptionId` /
`managementResourceGroup` to the accelerator's management subscription/RG.

### If you do **not** use the Enterprise Scale Accelerator

Set the three values yourself:

```bicep
param managementSubscriptionId = '11111111-1111-1111-1111-111111111111' // or '' for same sub
param managementResourceGroup  = 'esml-management-tools-rg'             // must differ from target RG
param logicAppName             = 'esml-genai-throttle-logic'
```

### Single-subscription AI Factory (e.g. a demo)

One subscription for everything — leave `managementSubscriptionId`/`targetSubscriptionId` empty and
just use a **separate management RG**:

```bicep
param targetSubscriptionId     = ''                         // same sub
param targetResourceGroup      = 'acme-1-project001-swc-dev-001'
param managementSubscriptionId = ''                         // same sub
param managementResourceGroup  = 'esml-management-tools-rg'  // separate RG (never throttled)
```

> **The scripts don't need any of this.** They run directly against the target with
> `-SubscriptionId <target>` / `-ResourceGroup <target-rg>` — no management subscription, no Logic
> App name.

---

## Per-environment budgets (dev / stage / production)

The **AI Factory core team** can set **different budgets for different AI Factory environments** of
the same project — e.g. a small cap for **dev**, a larger one for **stage**, and a production cap
for **production** — all governed from the one **AI Factory management subscription**.

Each environment is just another deployment of `main.bicep` pointed at that environment's project
subscription / resource group, with its own `budgetAmount`. Two common patterns:

| Level | How | Example |
|-------|-----|---------|
| **AI Factory global** (whole env) | `throttleScope='Subscription'` on the project subscription for that env | `dev` sub → \$5 000/mo, `prod` sub → \$50 000/mo |
| **Project team, per environment** | `throttleScope='ResourceGroup'` on the env's project RG (or `esmlAifactoryExists=true` + `env=dev|stage|prod`) | `project001` dev RG → \$500/mo, prod RG → \$5 000/mo |

With `esmlAifactoryExists=true`, set `env` (`dev` / `stage` / `prod`) and the project RG is derived
automatically per environment — deploy once per environment with a different `budgetAmount`:

```bicep
param esmlAifactoryExists = true
param env                 = 'dev'      // 'stage' / 'prod' for the other environments
param budgetAmount        = 500        // per-environment cap
```

---

## How to apply on a **Subscription** vs a **Resource Group**

Both the scripts and the Bicep take a `Scope` / `throttleScope`:

| Target | Scripts | Bicep |
|--------|---------|-------|
| **Whole subscription** | `-Scope Subscription -SubscriptionId <id>` | `throttleScope='Subscription'` (+ `targetSubscriptionId=<id>`) |
| **One project RG** | `-Scope ResourceGroup -ResourceGroup <rg>` | `throttleScope='ResourceGroup'` + `targetResourceGroup=<rg>` (+ `targetSubscriptionId=<id>`) |

- **Subscription scope**: the cost budget is subscription-wide; the Logic App enumerates every
  Cognitive Services account in the subscription. RBAC is granted at subscription scope.
- **Resource-group scope**: the cost budget is filtered to that RG; only accounts in that RG are
  throttled. RBAC is granted at that RG only (least privilege).
- `targetSubscriptionId` (Bicep) is optional — leave it empty to throttle the **subscription the
  deployment runs against**. Set it to throttle a **different** subscription than the one hosting
  the Logic App.

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
   Pass it as `managementResourceGroup` (**required, must differ from the throttled RG**), and
   optionally `managementSubscriptionId` if it lives in a different subscription than the target.
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
