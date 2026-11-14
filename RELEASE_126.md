# AI Factory v1.26: the mini release

**Release notes** &nbsp; | &nbsp; **14 November 2026** &nbsp; | &nbsp; branch `release/v1.26`

v1.26 is v1.25 made small. It has the same features as `main` on 14 November 2026 (commit `ebd300db`),
with everything removed that nothing uses, and with fixed waits in the pipelines replaced by checks of
the real condition. It adds no feature and changes no Bicep template, variable or API version.

Use it when you want the AI Factory as a submodule that clones in seconds:

```bash
git submodule add -b release/v1.26 --depth 1 https://github.com/jostrm/azure-enterprise-scale-ml azure-enterprise-scale-ml
```

`--aifactory-version 126` selects this branch in the launchers.

## The numbers

| | `main` (`ebd300db`) | `release/v1.26` | Change |
|---|---:|---:|---:|
| Files | 3,235 | 3,031 | 210 removed, 7 added |
| Tree size | 1,553 MB | 309 MB | 80% smaller |
| Shallow clone (`--depth 1 --single-branch`), time | 158 s | 19 s | 8 times faster |
| Shallow clone, download | 1,147 MB | 218 MB | 5 times smaller |
| Bicep files | 320 | 297 | 23 unused modules removed |
| Sleeps of 20 s or longer in the five pipeline and script files that changed | 16 | 4 | see "What got faster" |

The clone was measured once on a laptop on 14 November 2026, before the second removal round.
`main` has moved on since `ebd300db`; later commits on `main` are not in this branch.

## What "used" means here

A file stays when one of these reaches it, directly or through other files:

- the GitHub Actions workflows and the Azure DevOps pipelines, and through them the six ESAF scenarios
  (init factory, add scale set, upsert project, delete project, delete scale set, delete factory);
- the start and bootstrap scripts;
- the `azurefactory` CLI and SDK, and the API usage examples;
- the ML Model Factory, the Agent Factory and ESML v2;
- the Factory API and the configuration wizards, which read files from this repository;
- the Azure DevOps consumer repository that the release was checked against.

Tests and documents follow what they belong to. They never keep code alive on their own.

The rules are in [`.compact-repo.yml`](.compact-repo.yml). The file-by-file result of the last round is
in [`.compact-repo/report.md`](.compact-repo/report.md).

## What was removed

Nothing is lost: every removed file is still on `main`.

| Round | What | Files | Size |
|---|---|---:|---:|
| 1 | Installer binaries: the MAUI Config Wizard and the tutorial guide (current and older sets). The docs link them on `main`. | 56 | 1,226 MB |
| 1 | Files nothing reaches: parts of the ESML v1 SDK and its images, health model examples, one workspace file | 79 | 17 MB |
| 2 | Code that no pipeline, workflow, script, test or document names: 23 Bicep modules, 27 operator scripts in `esml-util`, 7 other scripts, 4 old dashboards, 4 ESML v1 pipeline definitions and 9 other files | 75 | 0.3 MB |

Per top-level folder: `environment_setup/` 142 files (1,227 MB), `esml/` 54 (17 MB), `healthmodel/` 7, `esmlrt/` 6, repository root 1. In total 210 files and 1,244 MB.

## What got faster

Three changes, each with a test that fails without it. They replace a wait of a fixed length with a check of
the real condition, or make an existing check look more often. Every time limit is the same as before.

| Where | Before | After |
|---|---|---|
| Azure DevOps project job, default container image step (05d) | 75 s of fixed waits | 15 s when the image exists, 45 s when it is imported; the registry is asked every 2 s |
| Azure DevOps project job, Foundry account wait (69a) | 10 or 15 minutes before the first look, then one look a minute | Looks from the start, every 10 s. An account that is ready after 2 minutes is reported after 7 minutes instead of 10 |
| Capability host wait, Azure DevOps and GitHub | One look every 20 s | Every 5 s |
| API Management SKU update, Azure DevOps and GitHub | One look every 30 s | Every 10 s |
| Application Gateway health in the scale-set bootstrap | One look every 30 s | Every 10 s |

Sleeps of 20 seconds or longer in the five changed files: 16 before, 4 after.

These are static counts and tests with a simulated clock. No live deployment was timed.

Left alone on purpose: five waits of 300 s, two of 600 s and four of 60 s on the delete and Foundry paths.
Nothing the scripts can read today shows when those are safe to end, so shortening them needs a live proof.
The largest candidates:

- GitHub `69-Rehydrate`: a fixed 300 s after a deployment that has already succeeded.
- GitHub capability host wait: it reads the host by a name that the Azure DevOps twin says cannot be
  guessed. If the twin is right, the step waits 15 minutes for nothing. One past run log settles it.
- Subnet release after a purge: 600 s in both twins.
- Project delete, step 6: 300 s.
- `azurefactory --help` takes 1.4 s against 0.2 s for a bare interpreter; lazy imports would save about
  0.4 s per call.

Retry, backoff, recovery and self-heal code was not touched. A wait that follows a failure is a backoff
and stays.

## How it was checked

| Check | Result |
|---|---|
| Main test suite, all five tiers, Ubuntu: `main` state against v1.26 | 9,616 tests on both. 9,424 passed and 166 failed on both, the same tests. The 166 failures are in tiers 4 and 5 and exist on `main`. |
| Main test suite, all five tiers, Windows | 9,616 tests on both. 9,431 passed and 166 failed on both, the same tests. |
| Bicep: all 25 entry points compiled, 696 flag cases | Passed on both, same 208 reachable templates. |
| Syntax phase (pipelines, workflows, scripts) | Passed on both. |
| 16 component test suites (CLI, ESML v2, ML Model Factory, Agent Factory and its agents, MCP, health model, lifecycle function, API examples and more), Ubuntu | Same result on both for every suite. In total 8,206 passed, 133 failed and 49 errors, the same tests on both. Most failures and errors are packages that the plain environment of this check does not install (for example `skops`, `nbformat` and, for the churn agent, `azure_esml`). |
| Azure DevOps consumer repository: 81 files and 10 folders it names inside this repository | All present. |
| Kept files that name a removed file | None. |

Not checked: no deployment to Azure was run from this branch. The checks are static analysis, compilation
and the offline test suites.

## Open decisions

These would make the branch smaller still. They are not applied, because each is a choice about what
v1.26 should contain.

1. **Three Config Wizard archives, 145 MB of the remaining size.** `install_config_wizard/` for Linux,
   Windows and macOS. The release manifest and the lifecycle function's install script read them from the
   checkout.
2. **89 more Bicep files outside the 25 main entry points.** The Bicep compile matrix reaches 208 of the
   320 files from its 25 entry points. Round 2 removed the 23 that nothing names. The other 89 are named
   by a test, a document or a script, and some belong to parts with their own deployment. The list is in
   the appendix.
3. **ESML v1.** The notebook templates in `copy_my_subfolders_to_my_grandparent/` stay whole, and with them
   61 files of the `esml/` and `esmlrt/` packages and the Azure ML SDK install folders. v1 is either kept
   whole or removed whole.
4. **The four named components stay whole:** Agent Factory, ML Model Factory, ESML v2 and the CLI. Their
   entry points do not reach every file in them.
5. **The documentation site source,** `documentation/gh-io/` (35 MB). The site is published from `main`.
6. **The tutorial guide's leftover files.** Its installers are removed; its manifest and distribution test
   still name them.

## How this branch was made

With [compact-repo](https://github.com/jostrm/compact-repo), a tool that follows the references from a
repository's entry points and removes what they do not reach:

```bash
compact-repo analyze . --base release/v1.26 --profile .compact-repo.yml --out <dir>
compact-repo apply   . --plan <dir>/plan.json --target release/v1.26 --update --push
```

To restore a file: `git checkout origin/main -- <path>`.

## Appendix: 89 Bicep files outside the reach of the 25 main entry points

The 25 entry points are the ones the Bicep compile matrix builds: `esml-common/main`, `esml-genai-1`
and the AI gateway. Some files below belong to parts with their own deployment (MCP, health model,
project automation, the simple application gateway), so this is a list to review, not a list to delete.

<details>
<summary>Show the 89 files</summary>

- `bootstrap/lib/all-factories-dashboard.bicep`
- `bootstrap/lib/simple-app-gateway-network.bicep`
- `bootstrap/lib/simple-app-gateway.bicep`
- `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/main.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/actionGroup.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/budget.resourcegroup.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/budget.subscription.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/logicApp.throttle.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/roleAssignment.resourcegroup.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/roleAssignment.subscription.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/scheduledQueryAlert.tokens.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/report-dispatch/main.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/deploy-automation.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/deploy-automation.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/modules/automationAccount.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry-usage-runbook.bicep`
- `environment_setup/aifactory/bicep/copy_to_local_settings/user_connectivity_dsvm/bicep-addOrUpdate-bastion-nsg-rule/007-main-bastionNsg.bicep`
- `environment_setup/aifactory/bicep/esml-common/ai-gateway/entra/aifactory-mcp-app-role.bicep`
- `environment_setup/aifactory/bicep/esml-common/modules-common/avdSessionHost.bicep`
- `environment_setup/aifactory/bicep/esml-common/modules-common/cloudflareTunnelVm.bicep`
- `environment_setup/aifactory/bicep/esml-genai-1/08-azure-mcp.bicep`
- `environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v2.bicep`
- `environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v3.bicep`
- `environment_setup/aifactory/bicep/esml-project/22-main.bicep`
- `environment_setup/aifactory/bicep/esml-project/23-add-dsvm.bicep`
- `environment_setup/aifactory/bicep/esml-project/24-add-aks.bicep`
- `environment_setup/aifactory/bicep/esml-util/007-main-bastionNsg.bicep`
- `environment_setup/aifactory/bicep/esml-util/100-aml-rbac.bicep`
- `environment_setup/aifactory/bicep/esml-util/23-add-dsvm.bicep`
- `environment_setup/aifactory/bicep/esml-util/24-add-aks.bicep`
- `environment_setup/aifactory/bicep/esml-util/25-add-user-to-bastion.bicep`
- `environment_setup/aifactory/bicep/esml-util/28-Initiatives.bicep`
- `environment_setup/aifactory/bicep/esml-util/28-policy.bicep`
- `environment_setup/aifactory/bicep/modules/addUserAsCoreteam.bicep`
- `environment_setup/aifactory/bicep/modules/addUserAsCoreteamBYOVnet.bicep`
- `environment_setup/aifactory/bicep/modules/addUserAsProjectMember.bicep`
- `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnet.bicep`
- `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnetRGs.bicep`
- `environment_setup/aifactory/bicep/modules/aifactory-dash-01.bicep`
- `environment_setup/aifactory/bicep/modules/azureMcpServer.bicep`
- `environment_setup/aifactory/bicep/modules/contributorRbacSimple.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/aiFoundry2025AvmOff.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/cs.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/main.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/add-project-capability-host.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-account-encryption.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-account-identity.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-project-identity.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-search-role-assignments.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/azure-storage-account-role-assignment.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/blob-storage-container-role-assignments.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/cosmos-container-role-assignments.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/cosmosdb-account-role-assignment.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/existing-vnet.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/format-project-workspace-id.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/network-agent-vnet.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/private-endpoint-and-dns.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/standard-dependent-resources.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/subnet.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/validate-existing-resources.bicep`
- `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/vnet.bicep`
- `environment_setup/aifactory/bicep/modules/dataBricks.bicep`
- `environment_setup/aifactory/bicep/modules/databricksManagedIdentityRBAC.bicep`
- `environment_setup/aifactory/bicep/modules/databricksPrivate.bicep`
- `environment_setup/aifactory/bicep/modules/databricksRBAC.bicep`
- `environment_setup/aifactory/bicep/modules/eventhub.bicep`
- `environment_setup/aifactory/bicep/modules/keyVaultExport.bicep`
- `environment_setup/aifactory/bicep/modules/machineLearning.bicep`
- `environment_setup/aifactory/bicep/modules/networking/dnsForwarding.bicep`
- `environment_setup/aifactory/bicep/modules/ownerRbac.bicep`
- `environment_setup/aifactory/bicep/modules/rbacGeneric.bicep`
- `environment_setup/aifactory/bicep/modules/rbacRGlevelAml.bicep`
- `environment_setup/aifactory/bicep/modules/virtualMachinePublic.bicep`
- `environment_setup/aifactory/bicep/personas/custom-roles.bicep`
- `healthmodel/bicep/main.bicep`
- `healthmodel/bicep/modules/action-group.bicep`
- `healthmodel/bicep/modules/reader-role.bicep`
- `mcp/infra/main.bicep`
- `mcp/infra/modules/application.bicep`
- `mcp/infra/modules/identity.bicep`
- `mcp/infra/modules/registry-pull.bicep`
- `mcp/infra/modules/role-assignments.bicep`
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep`
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/roles.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/application.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/identity.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/refresh.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/voice-roles.bicep`

</details>

