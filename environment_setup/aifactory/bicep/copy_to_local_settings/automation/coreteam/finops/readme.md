# Enterprise Scale AI Factory — AI FinOps

**Governance, visibility and control for AI / token-based cloud consumption.**

## Offline evidence bridge and optional native workbook

From the copied `automation` directory, the following only prints a local sample:

```powershell
python -I -B .\native_monitoring.py --input .\samples\monitoring-observations.six-reports.sample.json `
  --source sample --native-version 2 --aiFactory factory-a --scaleset 001 --project 001
```

This additive six-family fixture deliberately repeats project `001` in two
factories, with one quality-qualified and one unqualified modeled observation.
It is not a synchronized desktop fixture or live evidence. The earlier
`monitoring-observations.sample.json` fixture and its regression totals are unchanged.

For the **shared canonical scenario**, use the separately reviewed, fixed-day
18-scope fixture below. Its adjacent `.manifest.json` records scenario
`aifactory.monitoring-sample.v1`, original CRLF SHA-256/size and a portable
LF-normalized digest. It includes duplicate displayed project IDs across
`Demo AI Factory` and `Demo Factory B`, so exact compound filtering matters:

```powershell
python -I -B .\native_monitoring.py --input .\samples\monitoring-observations.canonical-reviewed.sample.json `
  --source sample --native-version 2 --aiFactory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev
```

This checked-in copy has no runtime dependency on another repository and is
never passed to a live loader. Its source markers and original finance evidence
survive round trips; native finance projections remain unavailable. The fixture
omits derived report-row `native_link`, which is not an observation input.

Native v2 (`agent-observations.v2.schema.json`) wraps each recognized
`aifactory.monitoring-observations.v1` row without splitting its original grain.
It retains requests/input/output tokens, ratio numerators/denominators, latency
sum/sample count, outcome inputs, cost bases, security counts, identity, model,
period and per-field provenance. Reverse `--observations-output` is the filtered
canonical envelope, including its source marker. Unknown fields fail instead
of being silently discarded. Files are bounded to 8 MiB and 10,000 rows.
The canonical CLI/API does **not** accept native v2 directly: use the canonical
reverse export for compatible observation-file consumers, or its recognized
`rows` in a reviewed API request. Sample exports remain sample and must never
enter the canonical live loader. Canonical API sample mode generates its own
scenario and does not accept externally supplied rows.
Native publication requires an explicit timezone-aware timestamp or period end;
none is guessed. Existing native v1 input is still supported. Omitting the
version retains v1 for legacy-compatible imports; select **2** for lossless
canonical round trips.

`--native-output`, `--output`, `--csv`, `--observations-output` and `--events`
write only explicitly requested local files. **Events are prepared, never
ingested.** Exact local serialization is not a claim of Azure ingestion size
acceptance, storage fidelity, query execution or Portal rendering.
The PowerShell wrapper `runbooks\Update-AgentMonitoringReport.ps1`
offers matching `NativeVersion`, `NativeObservationsPath`, `OutputPath`, `CsvPath`,
`CanonicalObservationsPath` and `EventsPath` options. Live imports require
explicit source and an authorized five-part scope manifest, not a login or
implicit Azure discovery.

V2 exposes the six existing report-family IDs. Missing operands stay null;
latency and success/quality rates use ratios of sums. User adoption is only
calculated from a single supplied population observation. Actual and amortized
cost need billing evidence; estimates need formula/inputs; currencies and cost
bases are never added together.

**Modeled** time-saving capacity preserves the canonical false-versus-null
qualification policy. **Qualified** capacity additionally requires explicit
quality approval and completion/baseline/effort evidence; monetary qualification
also needs an evidenced labor rate. Neither is cash realization. The additive
canonical `realized_benefit_amount`, `value_evidence` and `cost_evidence` fields
are preserved losslessly, including incomplete evidence. **Native verified
realized value, net/ROI and cost-per-accepted-outcome stay explicitly unsupported**:
use the canonical API's finance validation for approvals, exact currency/period/
scope and cost coverage/overlap checks. A supplied amount is never promoted to
verified benefit by this bridge. Original evidence is retained even when native
reporting withholds a calculated value.
Qualified v2 aggregates require **every visible row** to qualify. An incomplete
scope produces null qualified totals, not a sum of just its successful subset;
qualification counts still expose partial evidence. Historical v1 projections
and modeled formulas retain their existing semantics.

Native v2 metadata uses `value_class=observed|modeled|unavailable` plus descriptive
`value_tier`. Qualified labor capacity remains **modeled**; qualified outcome
counts are observed. `qualification.state`, `evidence_refs` and `reason` describe
outcome qualification, not financial approval. `cost_basis=actual|amortized|estimated`
keeps token estimates separate (`estimate_type=tokens`); legacy `costBasis=estimate`
is retained only as the compatibility spelling on projected rows.
Per-metric `status` is `available` or `unavailable`. Unsupported finance carries
an explicit reason, never a permissive modeled substitute. Non-outcome metrics
have qualification state `not-applicable`; supplied finance references are not
independently audited.

V2 evidence envelopes preserve canonical numbers up to absolute `1e100`, including
large integer precision. Native Python/KQL **projections** have the narrower
absolute `2^53-1` interoperability limit for inputs, intermediates and totals:
unsupported values are unavailable, never rounded or clamped. Lossless reverse
exports retain the original larger values; legacy native v1 retains its old limit.

The existing `modules\monitoring\agentMonitoringWorkbook.bicep` now accepts live
v1/v2 events. Phase 10 has a default-false `enableAgentMonitoring` parameter and
explicit `agentMonitoringWorkspaceResourceId`: enabling creates one stable
workbook in the existing common RG and links project dashboards to it. It adds
no diagnostics, ingestion, RBAC, schedules or workspace. Local tests/compiler
success do not prove deployment, KQL execution, source availability or Portal
rendering. Existing My Project dashboards retain their separate semantics.

## What is FinOps

FinOps = **Finance + DevOps**. It is the operating model and practice used to gain
**visibility, control and accountability** for cloud spending, while **optimizing costs and
maximizing the business value** of cloud investments — through collaboration between engineering,
finance and business teams.

> **FinOps is the operating model and practice used to gain visibility, control, and
> accountability for cloud spending, while optimizing costs and maximizing business value from
> cloud investments.**

FinOps is **broader than cost optimization** — it also covers cost management, forecasting and
financial accountability. The AI Factory community emphasizes the goal is not simply saving money,
but **maximizing the business value** of cloud investments.

- [What is FinOps — Microsoft Learn](https://learn.microsoft.com/en-us/cloud-computing/finops/overview)
- [What is FinOps — finops.org](https://www.finops.org/introduction/what-is-finops/)

| Term | Scope |
|------|-------|
| **Cost Optimization** | Reduce waste and lower costs (rightsizing, reservations, deleting unused resources). |
| **Cost Management** | Reporting, budgets, alerts, governance. |
| **FinOps** | Cost Management + Cost Optimization + Forecasting + Accountability + Business Value. |

With Azure OpenAI / Foundry, PTUs, PAYGO and fast-growing token consumption, the AI Factory applies
FinOps specifically to AI / token-based models — i.e. **"AI FinOps"**.

---

## AI FinOps, built in to the AI Factory

The Enterprise Scale AI Factory gives the **core team** a central operating model to **see, control
and account for** AI spend across every AI Factory **project subscription** and **resource group** —
while **project teams keep building and change nothing** in their solutions.

Two turn-key capabilities ship today, mapped to the FinOps Framework:

### 1. Understand usage & cost — *visibility, showback, usage tracking*

**AI Factory generated Foundry Token Report runbook**

- Real Foundry / model **token usage** from Log Analytics, per model and per AI Factory project
  (**showback / chargeback** by subscription or team).
- Adds **PAYGO-vs-PTU recommendations** to inform reservation / PTU planning.
- Scheduled, exported to **HTML / Markdown / PDF** for stakeholders.

➡ `../runbooks` (foundry-token-report)

**AI Factory dashboards — per project, per environment**

- **Azure Dashboards** generated by the AI Factory, one per **project** and per **environment**
  (dev / stage / production).
- Visualise **token usage, cost and budget burn-down** for each AI Factory project team, so both
  the core team and project teams see live consumption at a glance.

### 2. Manage & govern spend — *guardrails, budgeting, accountability*

**AI model consumption throttling (circuit breaker)**

- Set a **budget threshold** at AI Factory **global** (subscription), **project team** (resource
  group) or **per environment** (dev / stage / production).
- **Real-time and consumption-based**: reacts to your **actual Azure consumption / cost** —
  something **Azure Policy cannot do**.
- **Blocks over-consumption** at the threshold by cutting network access to the models (public
  access disabled and/or private endpoints rejected).
- Works for **all models** with no token counting or EA-discount conversion — it reads **billed
  consumption** directly.
- **Reversible**: turn it **ON** or **OFF**; exact state is restored on revert.
- Works with teams calling Foundry **directly** (no AI Gateway) **and** teams behind an **AI
  Gateway** — with **zero change** to the project team's solution.

➡ `./logicapps/aimodel-throttling-via-networkrule` (aimodel-throttling)

---

## How it maps to FinOps

| FinOps capability | AI Factory feature (today) |
|-------------------|----------------------------|
| Cost visibility & reporting | AI Factory generated Foundry Token Report (per model / project) |
| Cost dashboards | AI Factory dashboards (Azure Dashboards) per project / environment |
| Cost allocation | `CostCenter` tag on all RGs / resources |
| Showback | Cost per project / environment (AI Factory report + `CostCenter` tag) |
| Budgeting & forecasting | Per-scope budgets; PAYGO-vs-PTU guidance |
| Cost optimization | PTU-vs-PAYGO recommendations |
| Spending governance | Real-time consumption throttling |
| Usage tracking | Token usage from Log Analytics |
| Financial accountability | Central core-team control, per-team scope |

---

## Who does what

| Role | Responsibility |
|------|----------------|
| **AI Factory core team** | Owns the AI Factory **management subscription** and this FinOps tooling. Sets budgets, runs reports, operates the throttle centrally. |
| **AI Factory project team** | Runs models in an AI Factory **project subscription / resource group**. Gets visibility and guardrails applied **for** them — changes nothing in their solution. |

---

## Contents

| Path | What it is |
|------|------------|
| `logicapps/aimodel-throttling-via-networkrule` | Consumption circuit breaker (Logic App + managed identity, budget / token triggers). |
| `../runbooks` | Foundry Token Report + PAYGO/PTU recommendations. |
| `../runbooks/showback` | FinOps Showback report — cost per project / environment / cost center (replaces the legacy ADO `gov-cross-charging.yaml` pipeline). |

> **Note:** the Foundry Token Report currently lives in `../runbooks`. It is also a FinOps
> capability (visibility / showback) and can be moved under `finops/` for a single FinOps home.

---

## AI Factory FinOps: Implemented & Roadmap (Crawl → Walk → Run)

FinOps maturity grows from basic visibility to full accountability and business-value optimization.
Below is the AI Factory take on the FinOps capabilities — what ships today and where we're heading.
Not everything is covered yet; this is the direction of travel.

**Legend:** ✅ available · 🟡 in progress · ⬜ planned

### 🐣 Crawl — visibility & basic guardrails

| FinOps capability | AI Factory flavour | Status |
|-------------------|--------------------|--------|
| Cost visibility & reporting | Azure Cost Management + **AI Factory generated Foundry Token Report** per model / project | ✅ |
| Cost dashboards | **AI Factory dashboards** (Azure Dashboards) per project / environment | ✅ |
| Usage tracking | Token usage from Log Analytics per model / project / environment | ✅ |
| Budgeting & alerts | Per-scope budgets (subscription / project RG / environment) | ✅ |
| Cost allocation | **`CostCenter` tag** on all RGs / resources (by team / project / environment) | ✅ |

### 🚶 Walk — allocation, forecasting & optimization

| FinOps capability | AI Factory flavour | Status |
|-------------------|--------------------|--------|
| Showback | Cost per project / environment via **FinOps Showback runbook** (`../runbooks/showback`) + `CostCenter` tag | ✅ |
| Spending governance | **Real-time consumption throttling** (circuit breaker) | ✅ |
| Reservation / PTU planning | **PTU-vs-PAYGO analysis** across Foundry / OpenAI workloads | ✅ |
| Cost optimization | Per-environment SKUs & cluster rightsizing (e.g. 1 node in dev vs 3+ in stage / prod), deprecating idle deployments, model-tier optimization | ✅ |
| Chargeback | Formal chargeback by subscription / business unit | ⬜ |
| ML Forecasting future spend | ML-based token & cost forecasting per AI Factory project / environment | ⬜ |
| ML Anomaly detection | ML-based alerting on abnormal token / cost spikes per project | ⬜ |

### 🏃 Run — accountability & business value

| FinOps capability | AI Factory flavour | Status |
|-------------------|--------------------|--------|
| Financial accountability | Central core-team control, per-team ownership & budgets | ✅ |
| ROI & business-value measurement | Value per token / per use case, not just cost | ⬜ |
| FinOps maturity assessment | Crawl → Walk → Run self-assessment for the AI Factory | ⬜ |
| Continuous optimization | Automated PTU/PAYGO switching, savings-plan guidance | ⬜ |

> The goal is not simply saving money, but **maximizing the business value** of the AI Factory's
> AI investments — visibility and guardrails first, then allocation, forecasting and optimization,
> and finally accountability and ROI.


# AI FACTORY BASELINE INFO - HOW to get Resource names
## Whenever you need to add a variables in variables.yaml or .env
If .env is updated, then also this script needs to be updated: environment_setup\aifactory\bicep\copy_to_local_settings\github-actions\03a-GH-create-or-update-github-variables.sh

The same does not apply for Azure devops, where only variables.yaml needs updated: environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\variables\variables.yaml
## Naming convention - how do you retrieve the names of Azure resources in the AI Factory? 

You may see this in various places
- bicep: environment_setup\aifactory\bicep\modules\common\CmnAIfactoryNaming.bicep
- other powershell or bash scripts, tested and verified, such as: 
    - environment_setup\aifactory\bicep\scripts\delete-subnets-for-projects.sh
    - environment_setup\aifactory\bicep\scripts\delete-caphost-and-foundry-and-its-subnet.sh
    - environment_setup\aifactory\bicep\scripts\delete-services-if-disabled.sh
- Azure devops pipeine
    - variables.yaml environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\variables\variables.yaml
    - environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\esml-infra-project\jobs\job-2-genai-services.yaml
    - environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\esml-infra-project\jobs\job-1-genai-networking.yaml
    - environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\esml-infra-common\jobs\job-1-aif-cmn.yaml

Easiest way may be to look at the code in the Azure devops pipelines, since all conditional things is concidered, suchas  BYO_subnets. BYO_Vnets
See the following sections: How to find names of resources in the AI Factory,  Common resource group and vNetResource group, Project specific resource group


### How to find names of resources in the AI Factory

It depends if user uses Azure Devops or Github

If Azure devops, then the Variables.yaml should be used. It is located under their "aifactory" folder at this location with real values: aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml
- But hte template you can always use to know what variables exists. This is located here: environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\variables\variables.yaml

If Github, then the .env file at root should be looked at, a template exists here: environment_setup\aifactory\bicep\copy_to_local_settings\github-actions\.env.template  which you can use to see "which variables", but not the real values.  The real values should be read from root where the .env file is 

#### Common resource group and vNetResource group

See in the YAML how this is concatenated from variables.yaml at task `00_resolve_network_env_placeholders`

 BYO="$(BYO_subnets)"
      if [ "$BYO" = "true" ]; then
        NETWORK_ENV="$(network_env)"
        echo "BYO_subnets=true: using network_env=$NETWORK_ENV and provided subnet names"
      else
        NETWORK_ENV=""
        echo "BYO_subnets=false: network_env forced to empty; Bicep/PS1 will use naming convention"
        echo "##vso[task.setvariable variable=network_env]"
        echo "##vso[task.setvariable variable=subnetCommon]"
        echo "##vso[task.setvariable variable=subnetCommonScoring]"
        echo "##vso[task.setvariable variable=subnetCommonPowerbiGw]"
        echo "##vso[task.setvariable variable=subnetProjGenAI]"
        echo "##vso[task.setvariable variable=subnetProjAKS]"
        echo "##vso[task.setvariable variable=subnetProjAKS2]"
        echo "##vso[task.setvariable variable=subnetProjACA]"
        echo "##vso[task.setvariable variable=subnetProjACA2]"
        echo "##vso[task.setvariable variable=subnetProjDatabricksPublic]"
        echo "##vso[task.setvariable variable=subnetProjDatabricksPrivate]"
      fi

      VNET_RG="$(vnetResourceGroup_param)"
      VNET_NAME="$(vnetNameFull_param)"

      echo "Original vnetResourceGroup_param: $VNET_RG"
      echo "Original vnetNameFull_param: $VNET_NAME"
      echo "network_env value: $NETWORK_ENV"

      # Replace <network_env> placeholder in VNET_RG if it exists
      if [[ "$VNET_RG" == *"<network_env>"* ]]; then
        echo "Found <network_env> placeholder in vnetResourceGroup_param"
        VNET_RG="${VNET_RG//<network_env>/$NETWORK_ENV}"
        echo "Replaced with network_env value: $NETWORK_ENV"
      fi

      # Replace <network_env> placeholder in VNET_NAME if it exists
      if [[ "$VNET_NAME" == *"<network_env>"* ]]; then
        echo "Found <network_env> placeholder in vnetNameFull_param"
        VNET_NAME="${VNET_NAME//<network_env>/$NETWORK_ENV}"
        echo "Replaced with network_env value: $NETWORK_ENV"
      fi

      # If VNET variables are not set (empty or unexpanded), use naming convention
      if [ -z "$VNET_NAME" ] || [[ "$VNET_NAME" == \$\(vnetNameFull_param\)* ]]; then
        VNET_NAME="$(vnetNameBase)-$(admin_locationSuffix)-$(dev_test_prod)$(admin_commonResourceSuffix)"
        echo "VNET name not set, using naming convention: $VNET_NAME"
      else
        echo "Using provided VNET name: $VNET_NAME"
      fi

      if [ -z "$VNET_RG" ] || [[ "$VNET_RG" == \$\(vnetResourceGroup_param\)* ]]; then
        VNET_RG="$(admin_aifactoryPrefixRG)$(vnetResourceGroupBase)-$(admin_locationSuffix)-$(dev_test_prod)$(admin_aifactorySuffixRG)"
        echo "VNET resource group not set, using naming convention: $VNET_RG"
      else
        echo "Using provided VNET resource group: $VNET_RG"
      fi

      # Set resolved values as pipeline variables for reuse
      echo "##vso[task.setvariable variable=vnetResourceGroup_resolved]$VNET_RG"
      echo "##vso[task.setvariable variable=vnetNameFull_resolved]$VNET_NAME"

      echo "Resolved vnetResourceGroup: $VNET_RG"
      echo "Resolved vnetNameFull: $VNET_NAME"
      echo "Variables set: vnetResourceGroup_resolved, vnetNameFull_resolved, network_env=$NETWORK_ENV"

#### Project specific resource group

See in the YAML how this is concatenated from variables.yaml at task `05b_Check if resource exists`

      # Input parameters
      commonRGNamePrefix="$(admin_aifactoryPrefixRG)"
      projectNumber="$(project_number_000)"
      projectName="prj${projectNumber}"
      locationSuffix="$(admin_locationSuffix)"
      envName="$(dev_test_prod)"
      aifactorySuffixRG="$(admin_aifactorySuffixRG)"
      # uniqueInAIFenv="$(aifactory_salt)" # not used in this script. fuzzy match is used instead.
      resourceSuffix="$(admin_prjResourceSuffix)"
      prjResourceSuffixNoDash="${resourceSuffix#-}"
      twoNumbers="${resourceSuffix:2:2}"
      
      # Set project prefix and suffix from pipeline variables
      projectPrefix="$(projectPrefix)"
      projectSuffix="$(projectSuffix)"

      # Construct resource group name
      projectNameReplaced="${projectName/prj/project}"
      targetResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"

      # Debug resource group construction
      echo "=== RESOURCE GROUP CONSTRUCTION DEBUG ==="
      echo "commonRGNamePrefix: '$commonRGNamePrefix'"
      echo "projectPrefix: '$projectPrefix'"
      echo "projectNameReplaced: '$projectNameReplaced'"
      echo "locationSuffix: '$locationSuffix'"
      echo "envName: '$envName'"
      echo "aifactorySuffixRG: '$aifactorySuffixRG'"
      echo "projectSuffix: '$projectSuffix'"
      echo "Final targetResourceGroup: '$targetResourceGroup'"
