# AI Factory persona-access tutorial

Create a repeatable nine-persona access model without giving normal deployment
pipelines Entra group-administration privileges.

**Status:** opt-in `groups-v1`; legacy remains the default. Local tests are not
live Azure authorization certification. This tutorial does not use
`Run-Tutorial.ps1` or any `$contract` from another tutorial.

The [full specification](../../../../documentation/v2/20-29/25-personas-aifactory.md)
contains the evidence-backed v1.25 verdict, complete permission matrix, exact
role IDs, trust boundaries and migration details.

## 1. Inspect the example entirely offline

Use Python 3.10+; no Azure CLI, sign-in or Azure permissions are needed for this
step. Run from the Purple repository root:

```powershell
$purple = (Get-Location).Path
$personas = Join-Path $purple "environment_setup\aifactory\bicep\personas"
$inspection = python "$personas\inspect_manifest.py" --manifest "$personas\manifest.example.json"
if ($LASTEXITCODE -ne 0) { throw "Persona manifest inspection failed" }
$review = $inspection | ConvertFrom-Json
$review.state
$review.groups | ConvertTo-Json -Depth 8
$review.lake | ConvertTo-Json
$review.missing_security_reviews
```

Expected results:

| Field | Expected value |
|---|---|
| `state` | `offline-validated` |
| `cloud_checked` / `writes_performed` | Both `false` |
| `groups` | Nine calculated names and seeding keys, **not discovered object IDs** |
| `lake.authorized_path` | `mlops/v1/projects/project001/environments/dev` |
| `missing_security_reviews` | Three pending reviews for the fictional example |

Inspect `$review.custom_roles` for deterministic role GUIDs and exact permission
definitions. These are catalogue definitions, not proof that those roles exist
or are assigned. Only actual Azure discovery determines which service-data
grants apply. A successful offline inspection is **not** approval to deploy.

## 2. Understand the nine groups

| ID | Persona | Main boundary |
|---|---|---|
| `persona200` | Super admin | Owner on explicitly selected factory common/connectivity/project RGs; privileged Azure access management |
| `persona201` | Core team | Common/project infrastructure management; no general connectivity or RBAC administration |
| `persona210` | Project member | Project management/deployment/monitoring, minus access/credential-changing operations |
| `persona211` | Project admin | Member plus project resource-lock management; not Owner |
| `persona212` | Front-end developer | Project Functions, App Service/Web Apps, Container Apps and APIM |
| `persona213` | AI developer | Project AI services plus that project's read-only source-lake ACL |
| `persona214` | Database developer | Database-resource management; engine data grants are separate |
| `persona215` | Network & Security | Reviewed project-exclusive network scopes and project Key Vault Administrator |
| `persona216` | Project manager | Project cost/dashboard/observability and exact common Log Analytics workspace; no secrets |

Both core groups automatically receive the project-admin baseline in every
project. Member/admin/core/AI retain the safe project Search, inference and
Foundry-agent service-data bundle. Other ordinary personas do not get source
lake data access.

Except Project manager, project personas receive the exact secret baseline:
**GET, LIST, SET and DELETE**. It does not include purge, recover, backup/restore,
keys or certificates. Network & Security is the explicit elevated exception.

Membership is additive: PM + developer remains a developer; AI membership adds
that project's source access. Joining a second project's AI group adds its
authorized subtree, not the entire lake. A restrictive role is not a deny.

## 3. Prepare a real, per-project/per-environment manifest

Copy `manifest.example.json` into your **consumer repository**, for example
`access\dev-project001.json`, and replace every fictional GUID and resource name.
Do not overwrite existing configuration.

| Field | Required decision |
|---|---|
| `tenant_id`, `factory`, `scaleset`, `environment`, `project` | Exact identity boundary; `stage` in the UI maps to `test` |
| `seeding` | Existing reachable Key Vault holding administrator-published group records |
| `common_scope`, `project_scope` | Full RG ARM IDs matching the actual pipeline naming and subscription |
| `connectivity_scopes` | Only explicitly authorized owned connectivity RGs; leave empty otherwise |
| `project_network_scopes` | Project-exclusive subnets/NSGs or a dedicated project-RG VNet; never a whole shared common VNet |
| `log_analytics_resource_id` | Exact common workspace; workspace queries may expose other projects' logs |
| `lake` | Explicit HNS source account, filesystem, project and environment; required by the project model |
| `adoption` | Reviewed legacy-removal inventory and trusted isolated ingestion/admin object IDs |
| `security_review` | Keep all three flags false until the reviews are actually complete |

The project lake is required even when a legacy `enableProjectLakeAccess` flag
is missing or false. The old flag cannot bypass the new authorization model.
Invalid/missing lake configuration is rejected before seeded-ID discovery or
deployment. A common-only direct engine operation may omit it, but bootstrap
and pipeline flows validate the complete initial-project manifest.

Project group name:
`aif--<factory>--<scaleset>--<environment>--<project>--personaNNN`.
Core group name:
`aif--<factory>--<environment>--personaNNN`.
The seed key is `group-` followed by that name. Double-hyphen boundaries prevent
collisions; factory/scaleset slugs cannot themselves contain `--`.

Run step 1 again with `--manifest` pointing to your edited file. Group records
use bound JSON metadata, not bare GUIDs or positional `pNNN` arrays.

## 4. Bootstrap groups as the Entra administrator

This phase uses authenticated **read-only Azure/Graph calls** unless `--execute`
is added. Run in the intended tenant and verify the seeding subscription.
Discovery needs Graph `Group.Read.All`; creation needs `Group.ReadWrite.All`
and the applicable delegated directory rights. Publishing needs seeding-vault
secret GET/SET, including access to inspect soft-deleted entries.

```powershell
$manifest = "C:\path\to\consumer\access\dev-project001.json"
python "$personas\groups.py" --manifest "$manifest" --operation discover
python "$personas\groups.py" --manifest "$manifest" --operation create
```

`discover` previews reuse/publication and reports missing groups; `create`
previews creation of missing groups. **Neither command above writes.**

Only after explicit authorization for the reviewed changes may the administrator
append `--execute` to the chosen command. `discover --execute` publishes existing
groups but never creates them; `create --execute` can create and publish.
No membership, rename, Entra-role assignment or deletion is automated.

Serialize administrator runs. Duplicate display names, disabled/deleted seeds,
wrong bindings and conflicting object IDs fail rather than guessing. Rerunning
with unchanged groups/records creates no new groups or secret versions.
Historical groups require a separately reviewed canonical rename before explicit
adoption; old seed keys are not silently reused.

## 5. Select the model in the consumer configuration

Merge the selectors below into the **complete existing** `variables.json`; this
fragment is not a complete deployment configuration:

```json
{
  "dev": {
    "enablePersonas": true,
    "persona_access_mode": "groups-v1",
    "persona_access_manifest": "access/dev-project001.json",
    "project_number_000": "001"
  },
  "stage_prod": {
    "enablePersonas": false
  },
  "test": {
    "enablePersonas": true,
    "persona_access_manifest": "access/test-project001.json"
  },
  "prod": {
    "enablePersonas": true,
    "persona_access_manifest": "access/prod-project001.json"
  }
}
```

Paths are literal and relative to the consumer repository root. Selection is
`dev` baseline, then `stage_prod`, then exact `test`/`prod`. Every selected
manifest must match its environment, project and generated RG scopes. A new
project needs a different seven-group project set and manifest; it reuses the
two factory/environment core groups.

New `variables.json` and `variables.yaml` templates default to `enablePersonas: false`;
the deployment `.env.template` uses `ENABLE_PERSONAS=false`. False preserves all
configured legacy user/group fields and derives `persona_access_mode=legacy`.
True derives `groups-v1`, even if the template still says `persona_access_mode: legacy`,
and requires the reviewed manifest and seeded groups. Only booleans or exact
`true`/`false` strings are accepted; `"false"` is never treated as truthy.

The pipeline CLI treats empty process-environment flag aliases as absent because
GitHub represents an unset repository variable that way. Explicit empty JSON or
direct configuration values remain invalid. An absent flag never turns an
unsupported old `persona_access_mode` into legacy; the original mode is validated.

When the flag is absent, existing explicit `persona_access_mode` settings remain
supported. The configuration-preserving refresh keeps such opt-ins when introducing
the new default. JSON persona settings override CI defaults. Set `stage_prod` to
false for a Dev-only trial; explicitly enable other environments only with their
own reviewed manifests. Bootstrap accepts `AIF_ENABLE_PERSONAS` or `ENABLE_PERSONAS`.
The registered creation API must still advertise `persona-groups-v1`; the flag
does not bypass that gate. RGs already marked `AIF-Persona-Access=groups-v1` reject
false/legacy before deployment: switching the flag off is not a rollback or a
permission migration. It never adds old broad groups to a persona project.

Do not insert these group IDs into legacy `technical_admins_ad_object_id` or
`groups_*` arrays. The new bridge clears legacy human grant channels and consumes
the protected seeding entries itself.

## 6. Complete migration and run read-only preflight

Before adoption, remove or explicitly approve conflicting legacy grants.
The source account must have HNS enabled, Shared Key disabled and public blob
access disabled. Review inherited RBAC, ACL/default/owner entries, nested group
membership, historical keys/SAS, and identities/credentials reachable through
developer-controlled workloads.

AI humans get directory `r-x`, file `r--`, and ancestor `--x` only. Isolated
ingestion identities own/write source data. A writer can own files and change
ACLs, which is why this model does not silently give AI humans write access.
Keep lake credentials out of secrets/app settings readable by non-AI personas.
Source copied into Search, agents or databases has a separate data boundary.

From the consumer repository root:

```powershell
python "$personas\pipeline.py" --config ".\aifactory\variables.json" `
  --repo-root "." --environment dev --scope project --phase validate --format json

python "$personas\pipeline.py" --config ".\aifactory\variables.json" `
  --repo-root "." --environment dev --scope project --phase preflight --format json
```

`validate` is local configuration validation. `preflight` makes read-only Azure
calls: nine seed records must exist even before initial common/project001
creation. Existing deployments receive full access audits before templates run;
new RGs get seed/binding validation followed by full reconciliation after creation.

Exact legacy project assignments require both approved IDs and
`adoption.execute_migration: true`. Named legacy ACL removals require explicit
principal approval and the same migration flag. Inherited/common grants,
parent/sibling ACLs and ownership require separate reviewed remediation.
Never tick review flags merely to make a failing preflight pass.

## 7. Provision through the reviewed deployment path

Use the updated copied ADO/GHA common and phased project pipelines, or supported
registered scoped workers. They apply core access after common provisioning and
all project personas/core access after project provisioning. Normal deployment
identities do not create Entra groups.

**`pipeline.py --phase apply` changes Azure permissions.** It is not a preview.
Likewise, `groups.py --execute` changes directory/seeding state. Do not execute
either merely while following the offline tutorial.

Registered workers bind the manifest to the reviewed consumer commit and require
exact scope locks. Registered creation additionally requires the separate API to
advertise `persona-groups-v1`; an older server fails closed. Pink/MAUI packaging
is outside this folder. The legacy direct `22-main.bicep` route is blocked for
the new model; AML is supported through the phased project route.

Changing this checkout does not publish a release or update a consumer's pinned
Purple snapshot. Adopt a matched, approved source/pipeline/API version.

## 8. Run the unit tests

From Purple, use the existing pytest environment. No tenant, credentials, group
creation or RBAC changes are required:

```powershell
Set-Location "$purple\environment_setup\unit-tests\test-bicep"
python -m pytest unit\test_persona_policy.py unit\test_persona_groups.py `
  unit\test_persona_access.py unit\test_persona_lake.py unit\test_persona_pipeline.py `
  unit\test_persona_end_to_end.py unit\test_persona_inspect.py `
  unit\test_registered_personas.py -q
```

The end-to-end **unit** tests keep real group-record validation, permission
planning/reconciliation and ACL logic, faking only Azure CLI/DFS transports.
They cover missing/misbound/duplicate seeds, missing lake configuration,
unsafe storage settings, blocked reviews, core access, PM restrictions and
idempotent reruns. Lake tests reject malformed/duplicate inventory paths, file
ancestors and resource-type changes before ACL writes.

For production acceptance, separately authorize live positive/negative tests
with distinct persona users, overlapping memberships and two projects.
`integration\test_persona_authorization.py` requires `LIVE_AZURE=1` and
`PERSONA_AUTHORIZATION_CASES`; it otherwise skips. It does not replace authorized
canary tests of secret SET/DELETE and denied purge/key/certificate operations.
Firewall/network failures do not prove authorization isolation.

## Rollback and offboarding

Keep restricted grants and groups while reverting workload changes; never
automatically restore broad legacy RBAC, Shared Key or old credentials.
The RG marker prevents accidental legacy reruns through the supported bridge,
not tampering by privileged administrators.

Factory/project deletion preserves reusable Entra groups. Surviving common
resource grants and ACLs require separately reviewed exact cleanup; there is no
automated receipt-bound deprovision command. RG deletion alone is not complete
offboarding. An authorized directory administrator controls membership removal.

## Troubleshooting

| Symptom | Action |
|---|---|
| `explicit HNS lake configuration` | Supply the project/environment lake block; disabling a legacy flag is not a bypass |
| Missing or conflicting seed | Have the Entra administrator inspect bindings and use reviewed discover/create; do not replace IDs |
| Unresolved legacy access | Review exact assignments/ACLs and remove only approved access |
| Path is a file / inventory changed | Correct the path or pause concurrent ingestion, then rerun the complete audit |
| Insufficient Azure permissions | Authorize the required scoped executor; do not grant Entra privileges or broad data roles as a fallback |
| Unsupported creation API | Use a matched API with `persona-groups-v1`; do not bypass capability negotiation |
