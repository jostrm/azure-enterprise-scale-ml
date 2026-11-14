# AI Factory v1.26: the mini release

**Release notes** &nbsp; | &nbsp; **14 November 2026** &nbsp; | &nbsp; branch `release/v1.26`

v1.26 is v1.25 made small. It has the same features as `main` on 14 November 2026 (commit `ebd300db`),
with what nothing uses removed, with fixed waits in the pipelines replaced by checks of the real
condition, and with deployment steps that try again after a transient Azure error. It adds no feature.
No deployed Bicep template, no variable and no API version was changed.

ESML v1, the first-generation SDK with its notebook templates, is not part of this branch. It lives on
`main` and on `release/v1.24`. ESML v2 and the ML Model Factory are here.

Use it when you want the AI Factory as a submodule that clones in seconds:

```bash
git clone --depth 1 --single-branch --branch release/v1.26 https://github.com/jostrm/azure-enterprise-scale-ml azure-enterprise-scale-ml
git submodule add -b release/v1.26 https://github.com/jostrm/azure-enterprise-scale-ml azure-enterprise-scale-ml
git submodule absorbgitdirs azure-enterprise-scale-ml
```

Run them in the root of your own repository, then commit. They download 208 MB.

It takes three commands because the short form, `git submodule add -b release/v1.26 --depth 1 <url>`,
works only for a repository's default branch. For any other branch git first downloads the default
branch (`main`, 1,147 MB) and then stops with "is not a commit and a branch cannot be created from it"
(seen with git 2.43).

A colleague's fresh clone of your repository, and every pipeline job, gets the submodule with
`git submodule update --init --depth 1`. That works, but for the same reason it downloads `main` first:
1,151 MB in 63 s, measured on 14 November 2026. To get only the commit your repository pins (208 MB in
15 s), fetch that commit directly:

```bash
sha=$(git ls-tree HEAD azure-enterprise-scale-ml | awk '{print $3}')
git submodule init azure-enterprise-scale-ml
git init --quiet azure-enterprise-scale-ml
git -C azure-enterprise-scale-ml fetch --quiet --depth 1 https://github.com/jostrm/azure-enterprise-scale-ml "$sha"
git -C azure-enterprise-scale-ml checkout --quiet --detach FETCH_HEAD
git submodule absorbgitdirs azure-enterprise-scale-ml
```

`unit/test_release_consume_recipe.py` runs both blocks against a local repository and fails if they stop
working. The pipeline templates still use the standard checkout; see "Not done" for the change that
would give every job the 208 MB.

`--aifactory-version 126` selects this branch in the launchers.

## The numbers

| | `main` (`ebd300db`) | `release/v1.26` | Change |
|---|---:|---:|---:|
| Files | 3,234 | 2,643 | 604 removed, 13 added |
| Tree size | 1,553 MB | 294 MB | 81% smaller |
| Shallow clone (`--depth 1 --single-branch`), time | 128 s | 15 s | 8 times faster |
| Shallow clone, download | 1,147 MB | 208 MB | 5.5 times smaller |
| "Check out code" in this repository's own CI, per job | about 110 s | 13 to 20 s | 4 jobs per push |
| Azure DevOps job checkout of the submodule | 2,407 MB in 143 s | 1,151 MB in 63 s | see "What got faster" |
| Bicep files | 320 | 254 | 66 unused files removed (rounds 2 and 5) |
| PowerShell scripts (`.ps1`) | 81 | 47 | 34 removed |
| Shell scripts (`.sh`) | 96 | 56 | 40 removed |
| Sleeps of 20 s or longer in the five pipeline and script files that changed | 16 | 4 | see "What got faster" |

The clones and the checkouts were measured on one cloud machine on 14 November 2026, the clone on commit
`2f15e6eb`. The CI checkout times are from the GitHub Actions runs of `main` and of this branch.
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

Tests follow what they belong to. They never keep code alive on their own. Documents that the rules
keep by name still keep what they link to; that is one reason for the open decisions below.

The rules are in [`.compact-repo.yml`](.compact-repo.yml). The file-by-file report of a round is written
next to the plan, outside the branch: the profile sets `embed_report: false` since round 4, so the tool
no longer adds a `.compact-repo` folder to the root.

## What was removed

Nothing is lost: every removed file is still on `main`.

| Round | What | Files | Size |
|---|---|---:|---:|
| 1 | Installer binaries: the MAUI Config Wizard and the tutorial guide (current and older sets). The docs link them on `main`. | 56 | 1,226 MB |
| 1 | Files nothing reaches: parts of the ESML v1 SDK and its images, health model examples, one workspace file | 79 | 17 MB |
| 2 | Code that no pipeline, workflow, script, test or document names: 23 Bicep modules, 27 operator scripts in `esml-util`, 7 other scripts, 4 old dashboards, 4 ESML v1 pipeline definitions and 9 other files | 75 | 0.3 MB |
| 3 | ESML v1, by decision: the v1 SDK packages (`esml`, `esmlrt`, `esmlfac`), its notebook, pipeline, Data Factory, Databricks and settings templates, the Azure ML SDK install scripts for v1 developer machines, and the v1 documentation | 337 | 14 MB |
| Fix-up | Put back, because a kept document or test needs them: one Kong operator script and six tutorial packaging files | -7 | -0.06 MB |
| 4 | The root: the empty `__init__.py` and `meta/graphify/.gitignore` (see "Round 4: the root"; its other removed files were made on this branch) | 2 | 0.0 MB |
| 5 | Scripts and Bicep that nothing depends on: 43 Bicep files, 13 scripts and 6 files that only they used (see "Round 5: scripts and Bicep") | 62 | 0.9 MB |

Per top-level folder: `environment_setup/` 278 files (1,228 MB), `copy_my_subfolders_to_my_grandparent/` 200 (4 MB), `esml/` 79 (26 MB), `esmlrt/` 22, `documentation/` 9, `healthmodel/` 7, `bootstrap/` 3, `esmlfac/` 2, `usecase_code/` 1, `meta/` 1, repository root 2. In total 604 files and 1,259 MB. The folder names are the ones on `main`; "Round 4: the root" says where the kept parts are now.

What stays of the two folders that held ESML v1:

- `usecase_code/copy_my_subfolders_to_my_grandparent/` (at the root until round 4) keeps the 23 files that are current: the ML Model Factory
  templates in `dataops/azure-datafactory/` and `mlops/03_mlops_2026-09/`, and four readme files.
- The 16 images that `README.md` and two v2 documents show are kept; round 4 moved them from `esml/images/`
  to `documentation/images/esml/`.

## Round 4: the root

The repository root now shows four folders and four Markdown files. Joakim, before this round: "This is
a bad example. Too many folders, and md." Nothing was deleted that was in use: the components moved one
level down, and four files that nothing reads went. Every path under `environment_setup/`, `bootstrap/`
and `usecase_code/` before this round is unchanged, and the two start scripts stay at the root.

| At the root | Before (`4b6e7c1e`) | After |
|---|---:|---:|
| Folders (`.github/` and `.claude/` not counted) | 10 | 4 |
| Other dot-folders | 1 (`.compact-repo/`) | 0 |
| Markdown files | 13 | 4 |
| Other files | 7 | 6 |
| Files in the branch | 2,708 | 2,705 |

2,708 - 4 removed + 1 added = 2,705; 259 files moved. The four folders are `bootstrap/`, `documentation/`,
`environment_setup/` and `usecase_code/`; the four Markdown files are `README.md`, `RELEASE_126.md`,
`AGENTS.md` and `CLAUDE.md`. The other files are the two start scripts, `LICENSE`, `.gitignore`,
`.gitattributes` and `.compact-repo.yml`. `unit/test_repository_root_layout.py` (tier 1) fails when the
root grows again.

Removed (4 files):

- `.compact-repo/manifest.json` and `.compact-repo/report.md`, the report that compact-repo wrote into the
  branch. The profile now sets `embed_report: false`, so the report stays next to the plan.
- `meta/graphify/.gitignore`. The graph that `environment_setup/graphify/generate.py` writes to
  `meta/graphify/` by default is generated and never committed; the root `.gitignore` now ignores it.
- `__init__.py` at the root, an empty file. No folder at the root is a Python package, so no import
  resolves through it.

### Moved paths

| Old path | New path | Files | Who names the old path |
|---|---|---:|---|
| `esml-v2/` | `usecase_code/esml-v2/` | 71 | This repository: updated (build backend, pytest path, the ML Model Factory examples and notebooks, the churn agent's requirements, v2 docs). Links to `main` keep the old path, where it still exists. No consumer hit in the earlier scan. |
| `mcp/` | `usecase_code/mcp/` | 60 | This repository: updated. Pink names `mcp` in one file: follow-up, not changed here. |
| `healthmodel/` | `usecase_code/healthmodel/` | 80 | This repository: updated, including the two health model pipeline templates in `copy_to_local_settings`. Orange names `healthmodel/` once: follow-up, not changed here. |
| `copy_my_subfolders_to_my_grandparent/` | `usecase_code/copy_my_subfolders_to_my_grandparent/` | 23 | This repository: updated (ML Model Factory tests, template defaults, v2 docs). Consumers copy its subfolders; no consumer hit in the earlier scan. |
| `esml/images/` | `documentation/images/esml/` | 16 | `README.md` and two v2 pages: updated. `esml/` is gone. |
| `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md` | `.github/<same name>` | 4 | GitHub reads them in `.github/`. The architecture vault: updated. |
| `RELEASE_120.md`, `RELEASE_123.md`, `RELEASE_124.md`, `RELEASE_125.md`, `ROADMAP_MAIN.md` | `documentation/releases/<same name>` | 5 | The Agent Factory knowledge corpus (`config.example.json`, `mcp_gateway.py`) and the architecture vault: updated. The documentation site links them on `main`, where they still are. |
| | | **259** | |

Follow-ups for the consumers (not done here): orange's one `healthmodel/` path and pink's one `mcp` path
must gain the `usecase_code/` prefix when they move to v1.26. The consumer hits come from the scan before
this round (14 November 2026); the consumer repositories were not read again.

## Round 5: scripts and Bicep

Every `.ps1`, `.sh` and `.bicep` file was decided on its own. A file stays when a pipeline, a workflow, a
start or bootstrap script, the CLI, a Bicep module that is itself used, or a consumer repository reaches it,
or when `documentation/v2` or the readme next to it tells the operator to run it. A mention in a test, a
comment or another document is not a dependency. Joakim: "remove all not depending .ps1 or .sh or bicep".

| | Before (`2b32ad93`) | After |
|---|---:|---:|
| Files in the branch | 2,705 | 2,643 |
| Size | 294.7 MB | 293.8 MB |
| `.ps1` | 52 | 47 |
| `.sh` | 64 | 56 |
| `.bicep` | 297 | 254 |
| Folders at the root (`.github/` and `.claude/` not counted) | 4 | 4 |
| Markdown files at the root | 4 | 4 |
| README files | 274 | 274 |

2,705 - 62 = 2,643. Of the 413 scripts and Bicep files before this round, 56 went and 357 stay: 292
because a root reaches them, and 65 because they are operator commands or are reached through a computed
path (list below).

Removed (62 files):

| Group | Files | Why nothing needs them |
|---|---:|---|
| Foundry templates `09-ai-foundry-2025-v2.bicep` and `-v3.bicep`, the `modules/csFoundry/foundry-apim/` tree (main, 17 network modules, 4 parameter and metadata files), `aiFoundry2025AvmOff.bicep` and `keyVaultExport.bicep` | 26 | The pipelines and the Factory lifecycle deploy only `09-ai-foundry-2025-v4.bicep`; the rest was used only by v2 and v3 |
| The ESML v1 project template `esml-project/22-main.bicep` and the 7 modules only it used (Databricks, Event Hub, Azure ML, RBAC) | 8 | No pipeline deploys it; ESML v1 left in round 3 |
| Manual helpers in `esml-util/` and `esml-project/` (DSVM, AKS, bastion, IP rules, role helpers) and the bastion NSG pair in `copy_to_local_settings/user_connectivity_dsvm/` | 14 | No pipeline, script or operator page calls them |
| The two IP-rule scripts and the post-Bicep agentic script in `bootstrap/` | 3 | Only two commented-out lines in `00-start.sh` name them |
| Modules nothing names: `avdSessionHost`, `cloudflareTunnelVm`, `virtualMachinePublic`, `csFoundry/cs.bicep`, `networking/dnsForwarding.bicep` | 5 | No module statement uses them; the DNS forwarding guide now links the module on `main` |
| Scripts without a caller: Azure DevOps cross-charging step 120, the Databricks token and log-metrics scripts with the two Spark listener jars only the log-metrics script loaded, and a second copy of the finops `run-and-export.ps1` (the documented copy under `showback/` stays) | 6 | No caller |
| **Total** | **62** | 43 `.bicep`, 8 `.sh`, 5 `.ps1`, 3 `.json`, 2 `.jar`, 1 `.bicepparam` |

Tests followed their subjects. No test file was removed, and every check on a kept file is unchanged: 29
test cases went with the files they tested, one test was renamed, and three new cases check the kept AKS
module on its own instead of through the removed ESML v1 template. Ten test files changed:
`test_dns_policy_ownership.py`, and in `unit/`: `test_admin_object_ids.py`, `test_aks_outbound_type.py`,
`test_bootstrap_scaleset.py`, `test_defender_compute_baseline.py`, `test_diagnostics_telemetry.py`,
`test_foundry_model_deployments.py`, `test_key_vault_security_defaults.py`,
`test_private_foundry_capability_host.py` and `test_project_lake_acl.py`. Links in four documents and three
architecture notes now point at `main`.

<details>
<summary>The 65 files kept because they are operator commands or are reached through a computed path</summary>

- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep`: operator command (readme). Deployed by hand with main.bicepparam (using, line 1; command in lines 8-9 and in the folder readme.md)
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/actionGroup.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:181
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/budget.resourcegroup.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:206
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/budget.subscription.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:193
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/logicApp.throttle.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:151
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/roleAssignment.resourcegroup.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:172
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/roleAssignment.subscription.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:164
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/modules/scheduledQueryAlert.tokens.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/bicep/main.bicep:220
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/scripts/throttle-genai.ps1`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/readme.md (PowerShell variant); name...
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/scripts/throttle-genai.sh`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttle/readme.md:155
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/logicapps/report-dispatch/main.bicep`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/readme.md:173 ("Nothing deploys automatically"); repor...
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/Update-AgentMonitoringReport.ps1`: operator command (documentation/v2). documentation/v2/30-39/32-dashboards.md:1108
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/Update-FoundryTokenReport.ps1`: reached through a computed path. environment_setup/aifactory/bicep/copy_to_local_settings/automation/report_compute.py:25 (path built from parts; report_compute.py is an operator C...
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/deploy-automation.bicep`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/readme.md:245
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/Update-ShowbackReport.ps1`: reached through a computed path. environment_setup/aifactory/bicep/copy_to_local_settings/automation/report_compute.py:26 (path built from parts)
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/deploy-automation.bicep`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/readme.md:72
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/modules/automationAccount.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/deploy-automation.bicep:41
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/run-and-export.ps1`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/readme.md:39
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/governance/region-policy/New-EsafRegionPolicy.ps1`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/governance/region-policy/README.md:40
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/governance/region-policy/Remove-EsafRegionPolicy.ps1`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/governance/region-policy/README.md:47
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-publishing/publich-agent-to-Copilot.ps1`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-publishing/readme.md:117
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-publishing/publich-agent-to-TEAMS.ps1`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-publishing/readme.md:111
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry-usage-runbook.bicep`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/readme.md:157
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/run-foundry-usage-report.sh`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/readme.md:62
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/save-foundry-usage-queries.sh`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/readme.md:48
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/verify-and-configure-foundry-diagnostics.sh`: operator command (readme). environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/readme.md:33
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/report-local.ps1`: reached through a computed path. environment_setup/aifactory/bicep/copy_to_local_settings/automation/report_compute.py:359 (root / "report-local.ps1")
- `environment_setup/aifactory/bicep/copy_to_local_settings/automation/run-native-monitoring-sample.ps1`: operator command (documentation/v2). documentation/v2/30-39/32-dashboards.md:1185
- `environment_setup/aifactory/bicep/esml-util/000-switch-sub2_dev.ps1`: operator command (documentation/v2). documentation/v2/10-19/12-resourceproviders.md:16 (login step before the resource provider script)
- `environment_setup/aifactory/bicep/esml-util/25-add-users-to-kv-get-list-access-policy.ps1`: operator command (documentation/v2). documentation/v2/10-19/12-permissions-users-ad-sps.md:164; called by 26-add-esml-coreteam-member.ps1:123
- `environment_setup/aifactory/bicep/esml-util/26-add-esml-coreteam-member.ps1`: operator command (documentation/v2). documentation/v2/10-19/12-permissions-users-ad-sps.md:124
- `environment_setup/aifactory/bicep/esml-util/26-add-esml-project-member.ps1`: operator command (documentation/v2). documentation/v2/10-19/12-permissions-users-ad-sps.md:114
- `environment_setup/aifactory/bicep/esml-util/26-enable-resource-providers.ps1`: operator command (documentation/v2). documentation/v2/10-19/12-prerequisites-setup.md:359
- `environment_setup/aifactory/bicep/esml-util/27-create-private-dns-zones.ps1`: operator command (documentation/v2). documentation/v2/10-19/12-prerequisites-setup.md:408
- `environment_setup/aifactory/bicep/esml-util/28-policy.bicep`: operator command (documentation/v2). documentation/v2/10-19/14-networking-privateDNS.md:345 (optional policy the operator deploys by hand)
- `environment_setup/aifactory/bicep/esml-util/29-create-sp-or-update-oid-for-project.sh`: operator command (documentation/v2). documentation/v2/10-19/12-prerequisites-setup.md:372
- `environment_setup/aifactory/bicep/esml-util/32-create-azure-groups.sh`: operator command (documentation/v2). documentation/v2/10-19/16-ad-groups-personas.md:43
- `environment_setup/aifactory/bicep/modules/addUserAsCoreteam.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/esml-util/26-add-esml-coreteam-member.ps1:79
- `environment_setup/aifactory/bicep/modules/addUserAsCoreteamBYOVnet.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/esml-util/26-add-esml-coreteam-member.ps1:93
- `environment_setup/aifactory/bicep/modules/addUserAsProjectMember.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/esml-util/26-add-esml-project-member.ps1:136
- `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnet.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/esml-util/26-add-esml-project-member.ps1:111
- `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnetRGs.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/esml-util/26-add-esml-project-member.ps1:122
- `environment_setup/aifactory/bicep/modules/contributorRbacSimple.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnetRGs.bicep:89
- `environment_setup/aifactory/bicep/modules/monitoring/Deploy-AMPLS.ps1`: operator command (readme). environment_setup/aifactory/bicep/modules/monitoring/IMPLEMENTATION_SUMMARY.md:76 (weak: an implementation summary, not a guide)
- `environment_setup/aifactory/bicep/modules/ownerRbac.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/modules/addUserAsCoreteamBYOVnet.bicep:30
- `environment_setup/aifactory/bicep/modules/rbacGeneric.bicep`: used by an operator command. Used by environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnetRGs.bicep:101
- `environment_setup/aifactory/bicep/scripts/Copy-PrivateDnsRecords.ps1`: operator command (readme). environment_setup/aifactory/bicep/scripts/Copy-PrivateDnsRecords.md:63
- `environment_setup/aifactory/bicep/scripts/delete-caphost-and-foundry-and-its-subnet.sh`: operator command (documentation/v2). Protected clean-up script; documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md:115
- `environment_setup/aifactory/bicep/scripts/delete-subnets-for-projects.sh`: reached through a computed path. environment_setup/aifactory/bicep/scripts/delete-caphost-and-foundry-and-its-subnet.sh:607 ("${SCRIPT_DIR}/delete-subnets-for-projects.sh"); protec...
- `environment_setup/aifactory/bicep/scripts/enable-resource-providers.ps1`: operator command (readme). usecase_code/healthmodel/readme.md:60 (weak: the only script that registers Microsoft.CloudHealth for the health model; esml-util/26-enable-resourc...
- `usecase_code/10-azure-function/11_func_read_from_storage/deploy.ps1`: operator command (readme). usecase_code/10-azure-function/11_func_read_from_storage/README.md:68
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/deploy.ps1`: operator command (documentation/v2). documentation/v2/10-19/22-lifecycle-azure-function.md:88
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep`: reached through a computed path. usecase_code/10-azure-function/12_func_aifactory_lifecycle/deploy.ps1:105 (Join-Path $here infra/function-app.bicep)
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/roles.bicep`: used by an operator command. Used by usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep:286
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-factory-api-host.ps1`: operator command (documentation/v2). documentation/v2/10-19/22-lifecycle-azure-function.md:110
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-github-runner.ps1`: reached through a computed path. usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/register-management-runner.ps1:28 (Join-Path $PSScriptRoot)
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-lifecycle-runner.ps1`: operator command (documentation/v2). documentation/v2/10-19/22-lifecycle-azure-function.md:109
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/register-entra-app.ps1`: operator command (readme). usecase_code/10-azure-function/12_func_aifactory_lifecycle/README_More_Info.md:244
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/register-management-runner.ps1`: operator command (readme). usecase_code/10-azure-function/12_func_aifactory_lifecycle/README_More_Info.md:174
- `usecase_code/copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/main.bicep`: operator command (readme). usecase_code/copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md:57; also inside the profile root azure-datafactory/**
- `usecase_code/healthmodel/bicep/main.bicep`: reached through a computed path. usecase_code/healthmodel/src/aifactory_healthmodel/bootstrap.py:28 (HEALTHMODEL_ROOT / "bicep" / "main.bicep"); the CLI is run by github-actions/in...
- `usecase_code/healthmodel/bicep/modules/action-group.bicep`: used by an operator command. Used by usecase_code/healthmodel/bicep/main.bicep:115
- `usecase_code/healthmodel/bicep/modules/reader-role.bicep`: used by an operator command. Used by usecase_code/healthmodel/bicep/main.bicep:138
- `usecase_code/mcp/deploy/rollback.ps1`: operator command (readme). Protected failure path; usecase_code/mcp/readme.md:637
- `usecase_code/mcp/deploy/rollout.ps1`: operator command (readme). usecase_code/mcp/readme.md:598

</details>

## What got faster

Four changes, each with a test that fails without it. Three replace a wait of a fixed length with a check
of the real condition, or make an existing check look more often; every time limit is the same as before.
The fourth makes 13 Azure DevOps jobs download one commit instead of all history.

| Where | Before | After |
|---|---|---|
| Azure DevOps project job, default container image step (05d) | 75 s of fixed waits | 15 s when the image exists, 45 s when it is imported; the registry is asked every 2 s |
| Azure DevOps project job, Foundry account wait (69a) | 10 or 15 minutes before the first look, then one look a minute | Looks from the start, every 10 s. An account that is ready after 2 minutes is reported after 7 minutes instead of 10 |
| Capability host wait, Azure DevOps and GitHub | One look every 20 s | Every 5 s |
| API Management SKU update, Azure DevOps and GitHub | One look every 30 s | Every 10 s |
| Application Gateway health in the scale-set bootstrap | One look every 30 s | Every 10 s |
| Checkout in 13 Azure DevOps jobs (project, cross-charging, private MCP) | All history of the consumer repository and of this submodule: 2,407 MB in 143 s for the submodule | One commit of each: 1,151 MB in 63 s |

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

Existing retry, backoff, recovery and self-heal code was not removed or weakened. A wait that follows a
failure is a backoff and stays. What was added is under "What got more robust".

## What got more robust

Each change has a test that fails without it. None was run against Azure.

| What | Before | After |
|---|---|---|
| A transient Azure error in a deployment step: throttling, a 5xx, a timeout, "another operation is in progress", an identity that has not replicated yet | The step failed and the run was lost. In GitHub only step 69b tried again; in Azure DevOps five tasks retried on any failure | 31 more deployment steps of the common and project runs try again: at most 4 attempts, waits of 15 to 120 s, the same deployment name and inputs. Any other error still fails at the first attempt |
| A deployment that a cancelled or timed-out run left running | The next run was refused with `DeploymentActive` | The step waits for the earlier deployment to end (it looks every 10 s, for at most 20 minutes) and then deploys |
| The stage job of the GitHub common workflow, networking step | A space after a line-continuation backslash cut the command short: five parameters were not passed and the step could not succeed. The same line is on `main` | Fixed, with a test over every workflow and pipeline template |
| The command to add this branch as a submodule | The one-line form in this note failed with "is not a commit" after downloading `main` | Three commands that work, and a test that runs them |
| One Kong operator script and the tutorial guide's packaging scripts | Removed in round 1, although a kept document and a kept test need them | Put back |

The retry is one shared helper, `environment_setup/aifactory/bicep/scripts/modules/aif-retry.sh`. It decides
"transient" from error codes and phrases, never from bare numbers: "capacity 500" in a quota message is not
an HTTP 500. Steps that already had their own retry keep it: 68 (Logic Apps plan capacity), 69b, and the
Azure DevOps tasks 62, 63, 69a and 69b.

## How it was checked

| Check | Result |
|---|---|
| Main test suite, all five tiers, Ubuntu | Before: 9,616 tests, 9,424 passed, 166 failed. After round 1: the same, test by test. After round 2 and two of the three performance changes: 9,625 tests, 9,433 passed, 166 failed. No test that passed before fails. Three test cases left with the three removed Key Vault secret modules, and 12 are new. The 166 failures are in tiers 4 and 5 and exist on `main`. |
| Main test suite, all five tiers, Windows | Before and after round 1: 9,616 tests, 9,431 passed, 166 failed, the same tests. After round 2 and two of the three performance changes: 9,625 tests, 9,440 passed, 166 failed. No test that passed before fails. |
| Main test suite, default tiers, on the final commits | Green on Ubuntu and Windows after round 1, after round 2 and after the performance changes. |
| Bicep: all 25 entry points compiled, 696 flag cases | Passed on both, same 208 reachable templates. |
| Syntax phase (pipelines, workflows, scripts) | Passed on both. |
| 16 component test suites (CLI, ESML v2, ML Model Factory, Agent Factory and its agents, MCP, health model, lifecycle function, API examples and more), Ubuntu | Same result on both for every suite. In total 8,206 passed, 133 failed and 49 errors, the same tests on both. Most failures and errors are packages that the plain environment of this check does not install (for example `skops`, `nbformat` and, for the churn agent, `azure_esml`). |
| Azure DevOps consumer repository: 81 files and 10 folders it names inside this repository | All present before round 4. Round 4 moved `healthmodel/`, which it names once (see "Round 4: the root"). |
| Round 3, default tiers, Ubuntu and Windows | Green. |
| Round 3, all five tiers, before and after | 9,631 tests on both. Ubuntu: 9,439 passed and 166 failed. Windows: 9,446 passed and 166 failed. The same tests before and after. |
| Round 3, the 16 component suites, before and after | Same result for every suite, with one exception that is not caused by the round: the ESML v2 test `test_example_notebook_executes_actual_in2silver_merge_and_mlflow_inference` depends on row order and fails about every second run. The same job on the same commit passed when run again. |
| Kept files that name a removed file | 14 references, none of them a link that worked before. 11 are path mentions and consumer-side links in four v2 pages that still describe ESML v1 steps (pages 24, 32, 33 and 35), 2 are mentions in the architecture notes, and 1 is a false match in a test. Three links that did work were changed to point at `release/v1.24`. |
| The same check a second time, against the base file list | Found what the first check missed after rounds 1 and 2: 13 links in two readme files (health model examples, tutorial installers) and 7 files that a kept document or a kept test still needs. Fixed: the 7 files are back, the 13 links point at `main`. Two image links in `documentation/v2/30-39` were already broken on `main` and stay as they are. |
| Second, independent check of rounds 1 and 2 on `049b9d74` (cloud, Ubuntu) | All five tiers: none of the 9,424 tests that passed on the base fails; the same 166 fail on both; 3 cases left with their removed modules. All 25 Bicep entry files compile to the same ARM JSON as on the base, ignoring generator metadata and template hash. All 1,782 file references in 41 workflow and pipeline files resolve. A scratch repository with this branch as its submodule runs `01-start-v125-and-above.sh` offline, twice. |
| The same checks on `2f15e6eb`, which has round 3 and the changes under "What got more robust" (cloud, Ubuntu) | All five tiers: 9,872 tests, 9,680 passed, 166 failed. None of the tests that passed on the base fails; the same 166 fail on both; 3 cases left with their removed modules and 259 are new. The 25 Bicep entry files still compile to the same ARM JSON as on the base. The 19 component suites give the same result as on the base, test by test: 8,953 tests, 8,674 passed, 94 failed, 70 errors. The scratch repository check passes with the three commands above. |
| GitHub Actions on `2f15e6eb` | Green on Ubuntu and Windows (run 43579595936). |
| Round 4, all five tiers, before (`4b6e7c1e`) and after | 9,872 tests before, 9,874 after: the two new root-layout tests. Ubuntu: 9,680 passed before, 9,682 after. Windows: 9,687 and 9,689. 166 failed on both. No test that passed before fails. |
| Round 4, the 16 component suites | No test that passed before fails. |
| Round 5, default tiers, Ubuntu and Windows | Green on the probe. |
| Round 5, all five tiers, before (`4b6e7c1e`) and after | 9,872 tests before, 9,846 after: 29 cases went with their removed files, one test was renamed, three are new. Ubuntu: 9,680 passed before, 9,654 after. Windows: 9,687 and 9,661. 166 failed on both. No test that passed before fails. |
| Round 5, Bicep matrix | The same 25 entry points pass with 696 cases and the same 208 reachable templates: none of the 62 removed files was reachable. |
| Round 5, the 16 component suites | The same counts in every suite. |
| Round 5, consumers | The Azure DevOps consumer repository, the Factory API and the MAUI apps name none of the 62 files. |
| Every count in this table | Counts every test id. One test takes a random GUID as a parameter, so one id differs between any two runs. |

Not checked: no deployment to Azure was run from this branch. The checks are static analysis, compilation
and the offline test suites.

## Open decisions

These would make the branch smaller still. They are not applied, because each is a choice about what
v1.26 should contain.

1. **Three Config Wizard archives, 145 MB of the remaining 294 MB.** `install_config_wizard/` for Linux,
   Windows and macOS. The release manifest and the lifecycle function's install script read them from the
   checkout.
2. **46 Bicep files outside the 25 main entry points.** Round 5 checked each one and removed 43. The 46
   that stay belong to parts with their own deployment (MCP, health model, project automation, the
   simple application gateway, the lifecycle function, Data Factory) or are operator commands. The
   list is in the appendix.
3. **What is left of ESML v1.** v1 was removed in round 3. Two things remain: the 16 images under
   `documentation/images/esml/`, and four v2 pages that still describe v1 steps (24 legacy setup, 32, 33 and 35).
   The pages can be dropped, or rewritten to send the reader to `release/v1.24`.
4. **The four named components stay whole:** Agent Factory, ML Model Factory, ESML v2 and the CLI. Their
   entry points do not reach every file in them.
5. **The documentation site source,** `documentation/gh-io/` (35 MB). The site is published from `main`.
6. **The tutorial guide.** Its installers are removed and linked on `main`. The packaging scripts that its
   distribution test checks were put back (6 files, 56 KB). If the tutorial guide should not be built from
   this branch, remove the scripts, the test and the manifest together.

## Not done

No deployment to Azure was run from this branch. Beyond that:

1. **Pipeline jobs still download `main` with the submodule,** 1,151 MB per job. Fetching only the pinned
   commit is 208 MB in 15 s. It changes how every template checks out, so it needs a live run first.
2. **The fixed waits under "Left alone on purpose".** Each needs a live proof of the condition to wait for.
3. **Retries outside the common and project runs.** The gateway, dashboard and health model workflows are
   not wired, and PowerShell and Python have no shared retry helper yet.
4. **A soft-deleted Key Vault that blocks a project's vault name.** No step recovers or purges it.
5. **Repeated `az account set`:** 43 times in a GitHub project job, 38 in the Azure DevOps one, about 30 s
   per job. Left in, because each one protects a step against a subscription that an earlier step selected.
6. **CLI start-up.** Lazy imports would save about 15 ms of 95 ms on Linux, and only for commands that
   make no request.
7. **The stage networking fix on `main`.** `infra-common.yml` line 907 there still has the space.
8. **Wiring.** The Factory API and the configuration wizards do not offer 1.26 yet.

## How this branch was made

With [compact-repo](https://github.com/jostrm/compact-repo), a tool that follows the references from a
repository's entry points and removes what they do not reach:

```bash
compact-repo analyze . --base release/v1.26 --profile .compact-repo.yml --out <dir>
compact-repo apply   . --plan <dir>/plan.json --target release/v1.26 --update --push
```

To restore a file: `git checkout origin/main -- <path>`.

## Appendix: 46 Bicep files outside the reach of the 25 main entry points

The 25 entry points are the ones the Bicep compile matrix builds: `esml-common/main`, `esml-genai-1`
and the AI gateway. Some files below belong to parts with their own deployment (MCP, health model,
project automation, the simple application gateway). Round 5 removed the 43 that nothing deploys.

<details>
<summary>Show the 46 files</summary>

- `bootstrap/lib/all-factories-dashboard.bicep`
- `bootstrap/lib/simple-app-gateway-network.bicep`
- `bootstrap/lib/simple-app-gateway.bicep`
- `usecase_code/copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/main.bicep`
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
- `environment_setup/aifactory/bicep/esml-common/ai-gateway/entra/aifactory-mcp-app-role.bicep`
- `environment_setup/aifactory/bicep/esml-genai-1/08-azure-mcp.bicep`
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
- `environment_setup/aifactory/bicep/modules/ownerRbac.bicep`
- `environment_setup/aifactory/bicep/modules/rbacGeneric.bicep`
- `environment_setup/aifactory/bicep/personas/custom-roles.bicep`
- `usecase_code/healthmodel/bicep/main.bicep`
- `usecase_code/healthmodel/bicep/modules/action-group.bicep`
- `usecase_code/healthmodel/bicep/modules/reader-role.bicep`
- `usecase_code/mcp/infra/main.bicep`
- `usecase_code/mcp/infra/modules/application.bicep`
- `usecase_code/mcp/infra/modules/identity.bicep`
- `usecase_code/mcp/infra/modules/registry-pull.bicep`
- `usecase_code/mcp/infra/modules/role-assignments.bicep`
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep`
- `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/roles.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/application.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/identity.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/refresh.bicep`
- `usecase_code/40-agent-factory/40-aifactory-agent/infra/voice-roles.bicep`

</details>

