# Azure Deployment Stacks vs. AI Factory lifecycle governance

*Status: decision record (informational). Evidence date: 2026-10-25. Sources: the AI Factory repository (`main` and `release/v1.25`) and Microsoft Learn's Deployment Stacks pages listed at the end.*

## Introduction

[Azure Deployment Stacks](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deployment-stacks) (`Microsoft.Resources/deploymentStacks`) wrap an ARM/Bicep deployment in a resource that remembers which resources it manages. When you update or delete the stack, resources that are no longer in the template are either **detached** or **deleted** (`actionOnUnmanage`). **Deny settings** can block changes or deletes on managed resources.

The AI Factory already governs the full lifecycle of its Dev, Stage and Prod environments. Its ADO and GitHub Actions pipelines and the v1.25 Factory lifecycle code (`factory_lifecycle.py`, `factory_deletion_pipeline.py`) handle:

- creation and re-runs;
- selective service removal;
- whole-project or whole-factory deletion;
- coordination of shared connectivity hubs.

### Where stacks would live

Stacks are a way of *running* a deployment (`az stack sub create` instead of `az deployment sub create`), not a change to the Bicep code. Adopting them would leave the shared stage templates unchanged. It would change the ADO/GHA pipeline YAML and the scripts that read deployments back. The "Deploy to Azure" portal button can't create a stack at all, because Microsoft's documentation states that creating stacks in the portal "isn't implemented". For the portal package, a stack could only be a documented CLI route (`az stack sub create --template-uri …`).

Stacks don't replace the Dev/Stage/Prod concept. There would be one stack per environment and layer, for example `aif-<prefix>-common-dev`, `aif-<prefix>-project001-dev` and `aif-<prefix>-project001-prod`.

This document compares the two feature by feature. It explains why the AI Factory does **not** adopt Deployment Stacks as its lifecycle engine. The short version: stacks delete whatever the template no longer declares, in no order the caller controls. The AI Factory has to delete Foundry, AI Search and networking **in a specific order, with waits and purges, behind a reviewed and frozen plan**, and it must **never** touch shared or protected resources.

## Feature comparison

Legend: ✅ supported · ⚠️ partial or with caveats · ❌ not supported

| # | Capability | AI Factory | Azure Deployment Stacks |
|---|---|---|---|
| 1 | **Ordered deletion** (needed for Foundry and AI Search) | ✅ Phased order: capability hosts → AI Search shared private links → other resources → networking → resource groups (`factory_deletion_pipeline.py`, `phase()` / `ordered_resources()`), with dependency checks between phases | ❌ Deletes unmanaged resources with no caller-defined order, phases or dependency rules |
| 2 | **Waits between deletion steps** (Foundry agent subnet release) | ✅ Polls account capability hosts until gone; waits for subnet release after purge (pipeline step `06c2_Wait_For_Subnet_Release_After_Purge`; `delete-caphost-and-foundry-and-its-subnet.sh`) | ❌ No waits or custom steps |
| 3 | **Ghost capability-host cleanup** | ✅ Lists actual capability hosts and projects through REST and removes leftovers after a project was deleted in the portal | ❌ Only resources the template explicitly declared are managed; implicitly created ones are out of scope |
| 4 | **Soft-delete purge** (Foundry, Key Vault, others) | ✅ Purge steps (`18_Purge_Soft_Deleted`, `69-Purge-Soft-Deleted-Foundry-Before-Create`) so names can be reused | ❌ Deletes only; soft-deleted names keep blocking redeployment |
| 5 | **Idempotent re-runs of existing environments** | ✅ Templates skip creation of resources that exist (`*Exists` flags, e.g. `kv1 … if(!keyvaultExists)`, `cosmosdb … if(!cosmosDBExists …)`) | ⚠️ A skipped resource counts as *unmanaged*: with `deleteResources`/`deleteAll` it is **deleted** on the next run; with `detachAll` it simply drops out of the stack |
| 6 | **Selective service removal** (a feature flag turned off) | ✅ `delete-services-if-disabled.sh` deletes only disabled services and keeps dependencies (for example, AI Search is kept while Foundry's capability host needs it) | ⚠️ Removing a resource from the template deletes or detaches it, but without dependency checks between services |
| 7 | **Protection of shared and reusable resources** | ✅ Never deletes resources tagged `aifactory.bootstrap`, `platform`, `protected` or `reusable`, protected types, or Foundry *hub* workspaces (`protected()` in `factory_deletion_pipeline.py`) | ⚠️ `deleteAll` deletes everything the stack manages; only detach mode or careful template scoping prevents it |
| 8 | **Shared connectivity hub coordination** (v1.25) | ✅ Blob leases in the hub resource group (`hub_lock_foundation.py`) coordinate several factories; deletion retains shared-hub links it cannot prove it owns | ❌ No cross-deployment locking or lease coordination |
| 9 | **Reviewed, frozen deletion plan** | ✅ `AIFACTORY_LIFECYCLE_CONTRACT` freezes source, configuration, plan, scope, identity and expiry; execution needs a separate review | ❌ Stack update or delete acts immediately on the current template |
| 10 | **Receipts and recovery of uncertain writes** | ✅ Durable claims and receipts; uncertain writes are reported, not repeated | ⚠️ "Stack out of sync" error; recovery means redeploying the same template or bypassing the check |
| 11 | **Orphaned role-assignment cleanup** | ✅ `cleanup-project-orphan-roles.py` removes assignments for deleted principals | ❌ Not handled |
| 12 | **Capacity retries** (SKU and region fallback for AI Search, PostgreSQL, Container Apps) | ✅ `deploy-capacity-resource.py` retries the configured SKUs and fallback regions | ❌ One template run; no retry logic |
| 13 | **Data-plane and Microsoft Graph steps** (Key Vault secrets, Entra team groups and personas) | ✅ Handled by pipeline and bootstrap steps | ❌ Stacks can't delete Key Vault secrets; the Microsoft Graph Bicep provider isn't supported |
| 14 | **Name-based deployment lookups in scripts** | ✅ Pipelines name top-level deployments (`esml-p001-dev-…PrjDepl-66-ai-platform`, `…SubnetDeplProj`) and scripts read them back by name | ⚠️ Nested deployments keep their names, but `--name` names the *stack*; scripts reading top-level deployments would need `az stack … show` |
| 15 | **What-if preview** | ⚠️ Used for some workflows and the portal button (`az deployment … what-if`) | ⚠️ Not supported according to the known-issues page; a preview `az stack-whatif` command exists in the CLI |
| 16 | **Persona RBAC model** | ✅ Specialist personas may deploy but are explicitly denied `Microsoft.Resources/deploymentStacks/write` (tested in `test_persona_policy.py`) | ⚠️ Stack operations need their own roles (Deployment Stack Contributor or Owner) |
| 17 | **Dev / Stage / Prod environments** | ✅ First-class in ADO/GHA (environments, approvals, per-environment variables) | ⚠️ Neutral: you would need one stack per environment and layer; stacks have no environment concept |
| 18 | **Deny-assignments (block deletes or writes by anyone)** | ⚠️ Optional resource locks in one module (`aiFoundry2025AvmOff.bicep`); no factory-wide deny-assignments | ✅ `denyDelete` / `denyWriteAndDelete` with up to 5 excluded principals or groups |
| 19 | **One-command teardown of everything deployed** | ⚠️ Through the reviewed project and factory deletion flows (by design, not one command) | ✅ `az stack sub delete --action-on-unmanage deleteAll` |
| 20 | **Built-in managed-resource inventory** | ⚠️ Ownership records, the `register.json` catalog and the hosts inventory, owned by the AI Factory | ✅ Listed on the stack resource |
| 21 | **Scale limits** | No product limit beyond Azure's | 800 stacks per scope; 2,000 deny-assignments per scope |
| 22 | **Pipeline repair steps on managed resources** (Network Contributor grant, capability-host deletion, purges, subnet delegation) | ✅ Run as ordinary pipeline steps under the deployment identity | ⚠️ Blocked by deny settings unless the deployment identity is excluded; at most 5 excluded principals or groups |
| 23 | **Resources Azure creates on its own** (AKS node resource group, Databricks managed resource group, Foundry agent infrastructure) | ⚠️ Handled where needed by dedicated steps (for example capability-host and agent-subnet cleanup) | ❌ Not managed by the stack: no deny-assignments or cleanup |

## What the differences mean in practice

### 1. Foundry and AI Search need a deletion *procedure*, not just a list of resources
Microsoft's recommended teardown for a Foundry account with an agent capability host has several steps:

1. Delete the project capability hosts and wait.
2. Delete the account capability host (long-running; poll until gone).
3. Delete the projects, then the private endpoints.
4. Delete the account, then purge it.
5. Only after that, release the delegated agent subnet.

Skipping or reordering these steps leaves the subnet "in use" and blocks redeployment. AI Search's shared private links likewise have to go before the resources they point to. The AI Factory encodes this order (rows 1–4). A stack deletes whatever it no longer manages, without that order, waits or purges.

### 2. Automatic deletion conflicts with idempotent re-runs
AI Factory templates leave out resources that already exist (row 5), so re-running a pipeline never recreates or rewrites Key Vaults, storage accounts or Cosmos DB accounts. Under a stack with a delete mode, those skipped resources look unmanaged and **would be deleted on the second run**. Making stacks safe would mean rewriting every stage template to always declare every resource. That is a large change with a real risk of data loss if anything is missed.

### 3. Shared resources need judgement that a stack can't express
A factory can use a shared connectivity hub, common resources and bootstrap identities that other factories also depend on. The AI Factory proves ownership before deleting, keeps anything tagged or typed as protected, and coordinates shared hubs through leases (rows 7–8). A stack knows only "in my template" or "not in my template".

### 4. Governance: reviewed, frozen and recoverable
The v1.25 lifecycle freezes the deletion plan, requires a separate review, records receipts, and refuses to repeat uncertain writes (rows 9–10). A stack delete is immediate and would bypass that review. This is also why the persona policy denies stack writes to specialist roles (row 16).

### 5. Scripts that find deployments by name
The pipelines name their top-level deployments themselves, and several scripts read them back by name or name pattern:

| Script or step | Lookup | Effect of stacks |
|---|---|---|
| `scripts/ado/71_…`, `72_…`, `73_…DeleteIt.sh` | `az deployment sub list --query "[?starts_with(name, 'esml-p<nnn>-<env>-<loc>') && contains(name, '66-ai-platform')]"` | Breaks for the top-level deployment, because `--name` would name the stack |
| same scripts | Error search for the nested module `06-aiHubModule` | Keeps working: nested deployments keep the names the templates give them |
| `scripts/genDynamicNetworkParamFile.ps1` (line 499) | `Get-AzResourceGroupDeployment -Name "<prefix>SubnetDeplProj"` (reads `31-network` outputs) | Breaks |
| Pipeline step `67b-approve-adf-managed-private-endpoints` | `az deployment sub show --name $deplName` (reads outputs) | Breaks |
| `scripts/deploy-capacity-resource.py` | Names its deployments and reads the failed deployment's error by name | Breaks |

Each of these would have to switch to `az stack … show` and follow the stack's reference to its deployment. Microsoft's documentation doesn't state the name of the deployment object a stack creates, so this needs a live test first.

### 6. Pipeline repair steps and resources outside the stack
Several pipeline steps change managed resources after deployment: they grant the Foundry identity Network Contributor, delete capability hosts, purge soft-deleted resources and fix subnet delegation. Deny settings would block these unless the deployment identity is excluded, and a stack allows at most five excluded principals or groups. Resources Azure creates on its own are never managed by a stack, so the dedicated cleanup steps would still be needed (rows 22–23).

### 7. Where stacks are genuinely stronger
Stacks offer platform-enforced deny-assignments, a one-command teardown and a built-in inventory (rows 18–20). These are real benefits, but they don't need stacks to own the lifecycle. Delete protection for Prod can be added with resource locks or a deny-only stack in **detach mode**, which never deletes anything.

## Decision

Deployment Stacks are **not** adopted as the AI Factory's lifecycle engine. They lack ordered and phased deletion, waits, purges, dependency-aware selective removal, protection of shared resources, cross-factory coordination, and reviewed, frozen plans. In delete mode they also conflict with the idempotent "skip if it exists" re-run pattern and would delete existing resources.

### Effort and benefit of the options considered

| Option | Effort | Benefit | Risk | Verdict |
|---|---|---|---|---|
| **A. Portal factories only:** a documented `az stack sub create --action-on-unmanage detachAll --deny-settings-mode denyDelete` route next to the button, plus an explicit `deleteAll` teardown by the owner | ~0.5–1 day | Inventory, delete protection and easy teardown of throwaway Dev factories | Low: portal factories are greenfield and declare every resource, and nothing is deleted unless the owner asks | Possible; needs its own decision |
| **B. ADO/GHA pipelines in detach mode with deny settings:** swap the deploy calls per environment, adapt the ~8 name lookups (section 5), exclude the deployment identity, record the decision | ~1–2 weeks | Inventory and Prod delete protection | Medium: name lookups, deny exclusions, persona model | Deferred; would need an architecture decision |
| **C. Full lifecycle in delete mode** | ~4–8 weeks: make every stage template always declare its resources (removing the `*Exists` pattern), and reconcile with reviewed deletion, purges and ordering | Automatic cleanup | High: data loss if any resource is missed | Rejected |

Options A and B still leave deletion to the AI Factory's own flows. They use stacks only for what stacks do well (inventory and delete protection), never for deleting.

## Sources

**AI Factory repository**
- `bootstrap/lib/factory_deletion_pipeline.py`: phased and ordered deletion, protected resources, shared-hub link retention.
- `bootstrap/lib/factory_lifecycle.py`, `factory_lifecycle_contract.txt`: frozen, reviewed lifecycle contract.
- `bootstrap/lib/hub_lock_foundation.py`: Blob lease coordination of shared hubs.
- `environment_setup/aifactory/bicep/scripts/delete-caphost-and-foundry-and-its-subnet.sh`, `delete-services-if-disabled.sh`, `delete-subnets-for-projects.sh`, `cleanup-project-orphan-roles.py`, `deploy-capacity-resource.py`.
- `environment_setup/aifactory/bicep/scripts/ado/71_If_Error_AIFoundryHubAndProject_DeleteIt.sh`, `72_…`, `73_…`, `genDynamicNetworkParamFile.ps1`: name-based deployment lookups.
- `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml`: purge, wait and capability-host steps.
- `environment_setup/aifactory/bicep/esml-genai-1/02-core-infrastructure.bicep`, `04-databases.bicep`: `*Exists` conditions.
- `environment_setup/unit-tests/test-bicep/unit/test_persona_policy.py`: stack writes denied to specialist personas.

**Microsoft Learn** (retrieved 2026-10-25)
- [Create and deploy Azure deployment stacks in Bicep](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deployment-stacks)
- [Known issues for deployment stacks](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deployment-stacks-known-issues)
- [Azure CLI `az stack-whatif`](https://learn.microsoft.com/cli/azure/stack-whatif/group)

*Limitations: comparison based on documentation and source code. No Deployment Stack was deployed against the AI Factory templates. The exact name of the deployment object a stack creates was not confirmed in the documentation.*
