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
  - environment_setup/aifactory/bicep/modules/dataLake.bicep
  - environment_setup/aifactory/bicep/modules/kvCmnAccessPolicys.bicep
  - environment_setup/aifactory/bicep/scripts/kv_principal_object_ids.py
  - environment_setup/aifactory/bicep/scripts/preflight.sh
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_persona_policy.py
  - environment_setup/unit-tests/test-bicep/unit/test_persona_lake.py
  - environment_setup/unit-tests/test-bicep/unit/test_registered_personas.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_enrollment.py
  - environment_setup/unit-tests/test-bicep/integration/test_persona_authorization.py
  - environment_setup/unit-tests/test-bicep/unit/test_kv_access_policy_principals.py
  - environment_setup/unit-tests/test-bicep/unit/test_kv_principal_preflight.py
graph_symbols:
  - bootstrap/lib/registered_personas.py
reviewed_source: '3e9102ee + working tree; observed 2026-10-07; Key Vault principals 427b850f + working tree, 2026-10-20'
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

Legacy common Key Vault access policies (source 427b850f plus this change,
2026-10-20): `kvCmnAccessPolicys.bicep` grants only trimmed, lower-cased
GUID-shaped principals and skips anything else without failing the deployment.
The shipped `technical_admins_ad_object_id` placeholder would therefore leave
the common/admin vaults without an admin policy. `preflight.sh` closes that gap
with a gate that `kv_principal_object_ids.py` evaluates and that blocks even in
WARN_ONLY mode. `technical_admins_ad_object_id` (.env `PROJECT_MEMBERS`) must
be comma-separated GUIDs, or empty for none. `'null'` is rejected because the
GenAI project naming module would pass it to ARM role assignments. With
`--scope common` (or no scope), `databricksOID` must be one GUID, or empty for
no grant, when `enableDatabricks` is true. Only `13-rgLevel.bicep` reads it, so
project pipelines pass `--scope project`. The AzureDatabricks application ID is
rejected, because Key Vault needs the tenant's object ID.

A value in the pipeline environment is exactly what Bicep receives, so it wins.
ADO tasks map the principals explicitly, because secret variables are never
auto-mapped. Otherwise each of variables.json (per target environment overlay),
variables.yaml and .env is checked on its own. `groups-v1` skips both
principals, because the persona bridge clears the human channels and
`13-rgLevel.bicep` does not grant the Databricks policy in that mode. A
groups-v1 mode resolved in the pipeline environment also covers the settings
files. `PREFLIGHT_SKIP` still bypasses the whole preflight. These are offline
contracts. They do not prove which principals any deployed vault grants.

Deployment identities, runtime managed identities, human principals and provider service connections serve different purposes. Application runtime inference/search grants do not imply permission to deploy agents, mutate infrastructure or retrieve arbitrary secrets.

## Intended constraints

Adoption requires the reviewed manifest and matching scripts/pipelines. Merely placing new groups in old arrays is not migration. Effective access also depends on inherited Azure assignments, nested Entra membership, existing credentials, workload identities and service-specific data permissions.

Offline policy tests establish contract behavior; the cited opt-in live authorization test is not evidence of a live run in this vault task. Preserve security groups through deletion paths that explicitly require it.

See [[Factory-Scope-Model]], [[IaC-and-Private-Networking]], [[Trust-and-Authorization]], [[Lake-and-Data-Lineage]] and [[Index]].

Authority: [persona walkthrough](../../../environment_setup/aifactory/bicep/personas/readme.md), [release clarification](../../../RELEASE_125.md).
