---
id: identity-and-personas
status: observed
sources:
  - documentation/v2/20-29/25-personas-aifactory.md
  - environment_setup/aifactory/bicep/personas/readme.md
  - environment_setup/aifactory/bicep/modules/resourceGroupRbacUsers.bicep
  - environment_setup/aifactory/bicep/modules/storageRbacUsers.bicep
  - environment_setup/aifactory/bicep/modules/kvRbacAssignments.bicep
  - bootstrap/lib/registered_personas.py
  - bootstrap/lib/factory_enrollment.py
  - bootstrap/lib/create-new-aifactory-scaleset.sh
  - environment_setup/aifactory/bicep/modules/dataLake.bicep
  - environment_setup/aifactory/bicep/modules/kvRbacPrincipals.bicep
  - environment_setup/aifactory/bicep/modules/keyVault.bicep
  - environment_setup/aifactory/bicep/modules/common/keyVaultDefaults.json
  - environment_setup/aifactory/bicep/scripts/kv_principal_object_ids.py
  - environment_setup/aifactory/bicep/scripts/preflight.sh
  - environment_setup/aifactory/bicep/modules/common/objectIds.bicep
  - environment_setup/aifactory/bicep/modules/contributorRbac.bicep
  - environment_setup/aifactory/bicep/modules/common/CmnAIfactoryNaming.bicep
  - environment_setup/aifactory/bicep/esml-common/main/11-rgCommon.bicep
  - environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep
  - environment_setup/aifactory/bicep/esml-project/22-main.bicep
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_persona_policy.py
  - environment_setup/unit-tests/test-bicep/unit/test_persona_lake.py
  - environment_setup/unit-tests/test-bicep/unit/test_registered_personas.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_enrollment.py
  - environment_setup/unit-tests/test-bicep/unit/test_github_json_bootstrap.py
  - environment_setup/unit-tests/test-bicep/integration/test_persona_authorization.py
  - environment_setup/unit-tests/test-bicep/unit/test_kv_access_policy_principals.py
  - environment_setup/unit-tests/test-bicep/unit/test_kv_principal_preflight.py
  - environment_setup/unit-tests/test-bicep/unit/test_admin_object_ids.py
  - environment_setup/unit-tests/test-bicep/unit/test_key_vault_security_defaults.py
graph_symbols:
  - bootstrap/lib/registered_personas.py
reviewed_source: '3e9102ee + working tree; observed 2026-10-07; Key Vault principals 427b850f + working tree, 2026-10-20; admin object IDs 32458a63 + working tree, 2026-10-20; GitHub federation subject 98711370 + working tree, 2026-10-22; Key Vault RBAC and secret expiry 3f0711f0 + working tree, 2026-10-23'
---
# Identity and personas

## Observed source distinction

Legacy group-principal support is not a complete nine-persona permission model. Older positional arrays and repeated team IDs do not make roles distinct. The current working tree adds opt-in `groups-v1`; its documented default remains `legacy`, and release notes explicitly do not establish availability in old packages.

The authoritative [persona specification](../../v2/20-29/25-personas-aifactory.md) maps stable personas, executable custom roles, scoped discovery, privileged seeding and adoption/migration gates. Link to that matrix rather than keeping a second permission table here.

Management visibility, resource administration and data access are different. Common-lake ACLs cannot restrict access already granted by broad storage RBAC. Project administrator labels do not authorize unrestricted common/hub access. The new exact project-vault secret GET/LIST/SET/DELETE baseline is neither the older read-only baseline nor the broader Secrets Officer wildcard.

The canonical common-storage enrollment projection preserves the datalake's
tag-driven shared-key policy: `AIF-Persona-Access=groups-v1` disables shared keys;
legacy or absent persona tags retain the legacy policy. Enrollment does not
re-enable keys to make coordination work.

Common Key Vault principals (source 427b850f, 2026-10-20; RBAC since 3f0711f0 plus this change,
2026-10-23): `kvRbacPrincipals.bicep` (formerly the access-policy module `kvCmnAccessPolicys.bicep`)
grants only trimmed, lower-cased GUID-shaped principals and skips anything else without failing the
deployment. The shipped `technical_admins_ad_object_id` placeholder would therefore leave
the common/admin vaults without an admin role assignment. `preflight.sh` closes that gap
with a gate that `kv_principal_object_ids.py` evaluates and that blocks even in
WARN_ONLY mode. `technical_admins_ad_object_id` (.env `PROJECT_MEMBERS`) must
be comma-separated GUIDs, or empty for none. `'null'` is rejected, although the
Bicep consumers now treat it as none (see below). With
`--scope common` (or no scope), `databricksOID` must be one GUID, or empty for
no grant, when `enableDatabricks` is true. Only `13-rgLevel.bicep` reads it, so
project pipelines pass `--scope project`. The AzureDatabricks application ID is
rejected, because Key Vault needs the tenant's object ID.

A value in the pipeline environment is exactly what Bicep receives, so it wins.
ADO tasks map the principals explicitly, because secret variables are never
auto-mapped. Otherwise each of variables.json (per target environment overlay),
variables.yaml and .env is checked on its own. `groups-v1` skips both
principals, because the persona bridge clears the human channels and
`13-rgLevel.bicep` does not grant the Databricks role in that mode. A
groups-v1 mode resolved in the pipeline environment also covers the settings
files. `PREFLIGHT_SKIP` still bypasses the whole preflight. These are offline
contracts. They do not prove which principals any deployed vault grants.

Technical admin object IDs (source 32458a63 plus this change, 2026-10-20) follow
one rule, `normalizedObjectIds` in `modules/common/objectIds.bicep`. It trims and
lower-cases every entry, drops empty and `'null'` entries, and removes duplicates
in first-seen order. So it accepts everything the gate accepts and also tolerates
empty or `'null'` entries. Importing a user-defined function compiles a template
to ARM languageVersion 2.0, which changes how its `existing` resources deploy. So
only `CmnAIfactoryNaming.bicep`, already 2.0, imports it; its
`p011_genai_team_lead_array` feeds the GenAI RBAC modules. The classic templates
`11-rgCommon.bicep`, `13-rgLevel.bicep` and `kvRbacPrincipals.bicep` (before its
GUID filter) inline the exact body. `esml-project/22-main.bicep` inlines it too,
although it already compiles to 2.0 and so could import it.
`test_admin_object_ids.py` pins every copy and keeps the classic templates classic.
Role-assignment names are seeded with the object ID: `contributorRbac.bicep` uses
`guid('<id>-contributor-<rg id>')`. So spacing or case in the variable no longer
renames an assignment, which would fail a redeploy with RoleAssignmentExists (409).
Already-normalized input keeps its earlier names. A factory deployed with
upper-case IDs gets new names once, and that redeploy fails with the 409 until the
older assignment for the same principal, role and scope is deleted.
`contributorRbac.bicep` labels an assignment with its object ID when
`technical_admins_email` has fewer entries than the IDs; before, that case failed
11-rgCommon and 22-main with an index out of bounds. The manual `esml-util`
templates still parse the list themselves.

Key Vault permission model (3f0711f0 plus this change, 2026-10-23): every vault purple creates uses Azure
RBAC (`enableRbacAuthorization: true` in `keyVault.bicep`, now the only vault module; `kvRbacKeyVault.bicep`
and the unused `kvAccessPolicy.bicep` are gone). Before, `keyVault.bicep` used access policies unless the
factory tag was `AIF-Persona-Access=groups-v1`, so the common, common-admin and legacy `esml-project`
vaults were access-policy vaults; GenAI project vaults were already RBAC. Each former access policy is the
equivalent built-in role for the same principal, granted by `kvRbacPrincipals.bicep` with the role
assignment name `guid(vault id, object ID, role ID)`:

| Vault | Principal | Former policy | Role now |
|---|---|---|---|
| common, common-admin | technical contact + technical admins | secrets all | Key Vault Secrets Officer |
| common | AzureDatabricks app (`databricksOID`), common SP, common ADF | secrets get / get,list | Key Vault Secrets User |
| common-admin | common SP, common ADF | secrets get,list / get | Key Vault Secrets User |
| common (from `02-core`) | technical contact + project team leads; project SP | secrets get,list; get | Key Vault Secrets User |
| `esml-project` kv1/kv2 | technical contact + team leads | secrets get,list,set | Key Vault Secrets Officer |
| `esml-project` kv1 | project SP, ADF, Databricks | secrets get / get,list | Key Vault Secrets User |
| `esml-project` kv1, kv2 | classic AML workspace, managed AML workspace (`alsoManagedMLStudio`) identities | AML added its own policy | Key Vault Administrator |
| project vault (`pgFlexibleServer.bicep`) | PostgreSQL CMK identity | keys get,wrapKey,unwrapKey | Key Vault Crypto Service Encryption User |

Human grants keep their persona gate (legacy mode only; groups-v1 grants people through the persona
bridge), and the service grants keep their original conditions, so groups-v1 factories, whose vaults were
already RBAC, change nothing. The deployment identity needs `Microsoft.Authorization/roleAssignments/write`
on the vaults: the bootstrap gives it Contributor and User Access Administrator on each subscription, which
also covers switching an existing vault's permission model. Readers outside Bicep already used RBAC: the
MCP (`mcp/infra/modules/role-assignments.bicep`), the lifecycle Function (`infra/roles.bicep`) and the
seeding vault (created with `--enable-rbac-authorization true`; a BYO access-policy seeding vault keeps
its policies).

Secret and key expiry: every secret and key a purple template creates gets `exp` from one deployment
parameter, `keyVaultSecretExpiry`, whose default is one year after the deployment runs
(`dateTimeToEpoch(dateTimeAdd(utcNow(), 'P1Y'))`; the rule is `secretExpiresAfter` in
`modules/common/keyVaultDefaults.json`). ARM allows no `variables()` in a parameter default, so each
template inlines that expression and `test_key_vault_security_defaults.py` pins every copy. Entry
templates pass their value down, so one override sets it everywhere. A secret the template rewrites on
every run gets a new version with a new expiry; secrets written only on first deployment (for example
the project seeding copies behind `!keyvaultExists`, the PostgreSQL connection string) are not renewed
and must be rotated within the year. An ARM PUT returns an existing key unchanged, so `keyVaultKey.bicep`
also sets a rotation policy: Key Vault creates a new version 30 days before expiry, valid one more year,
which services that use the versionless key URI pick up (AKS disk encryption sets need automatic key
rotation enabled for that). The scripts that run `az keyvault secret set` (`29`, `29b`, `32`,
`create-new-aifactory-scaleset.sh`) pass `--expires` one year ahead in UTC (`AIF_KV_SECRET_EXPIRES`
overrides), and the MCP rollout sets `expires_on` the same way. The VM modules
(`virtualMachinePrivate.bicep`, `virtualMachinePublic.bicep`, `avdSessionHost.bicep`) still carry their
own fixed, already past expiry and are not yet migrated.

Migration of an existing access-policy vault (common, common-admin, legacy project vaults). Switching
`enableRbacAuthorization` makes Key Vault ignore every access policy at once, and in the template the role
assignments are created after the vault update. So grant the roles first:

1. Inventory: `az keyvault show -n <vault> --query "properties.accessPolicies[].{oid:objectId,secrets:permissions.secrets,keys:permissions.keys,certs:permissions.certificates}"`.
   Map each principal with the table above. Policies added by hand need a role too: secrets get/list ->
   Key Vault Secrets User, secrets set/delete -> Secrets Officer, keys wrap/unwrap -> Crypto Service
   Encryption User, certificates -> Certificates Officer, all of it -> Key Vault Administrator.
2. Pre-create the template's own grants with the same deterministic names, so the later pipeline run is
   idempotent instead of failing with RoleAssignmentExists (409): run `modules/kvRbacPrincipals.bicep`
   against the existing vault with the same inputs, for example
   `az deployment group create -g <common-rg> -f modules/kvRbacPrincipals.bicep -p keyVaultResourceName=<vault> principalId=<technicalContactId> additionalPrincipalIds='["<admin oid>"]' keyVaultRole=secretsOfficer`
   (add `principalType=ServicePrincipal` for an SP or managed identity). Role assignments on a vault
   that still uses access policies are inert, so this step is safe. Create the hand-added principals'
   roles with `az role assignment create --assignee-object-id ... --assignee-principal-type ... --role ... --scope <vault id>`.
3. Wait for propagation (up to about ten minutes), then run the common pipeline (`13-rgLevel.bicep`
   switches the common and admin vaults), then each project pipeline (`02-core` grants the project's team
   leads and project SP on the common vault).
4. Verify `properties.enableRbacAuthorization` is true and that each consumer still reads its secrets
   (Databricks Key Vault-backed scopes, ADF linked services, pipelines, people). The old policies stay
   stored but unused; `az keyvault update --enable-rbac-authorization false` rolls back to them.

Deployment identities, runtime managed identities, human principals and provider service connections serve different purposes. Application runtime inference/search grants do not imply permission to deploy agents, mutate infrastructure or retrieve arbitrary secrets.

GitHub deployment federation (observed on a real bootstrap, 2026-10-22): a federated credential works only with the
exact `sub` GitHub signs. For repositories created after 2026-07-15 that is the immutable
`repo:OWNER@OWNER_ID/REPO@REPO_ID:environment:ENV`, which GitHub can't turn off; older repositories keep
`repo:OWNER/REPO:environment:ENV`. `factory_enrollment.github_subject_prefix` derives the prefix from
`GET repos/OWNER/REPO` and its `actions/oidc/customization/sub`, uses GitHub's `sub_claim_prefix` only when it names
exactly that repository, and refuses a customized subject. The registered bootstrap records the result as the
review's `federation`, which the Factory API's ownership handoff checks the credential against; Simple mode
(`create-new-aifactory-scaleset.sh`) uses the same rule. A credential with another subject is never replaced: a
factory federated with the classic subject on a newer repository fails `azure/login` with `AADSTS700213` until its
credential is migrated explicitly.

## Intended constraints

Adoption requires the reviewed manifest and matching scripts/pipelines. Merely placing new groups in old arrays is not migration. Effective access also depends on inherited Azure assignments, nested Entra membership, existing credentials, workload identities and service-specific data permissions.

Offline policy tests establish contract behavior; the cited opt-in live authorization test is not evidence of a live run in this vault task. Preserve security groups through deletion paths that explicitly require it.

See [[Factory-Scope-Model]], [[IaC-and-Private-Networking]], [[Trust-and-Authorization]], [[Lake-and-Data-Lineage]] and [[Index]].

Authority: [persona walkthrough](../../../environment_setup/aifactory/bicep/personas/readme.md), [release clarification](../../../RELEASE_125.md).
