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
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_persona_policy.py
  - environment_setup/unit-tests/test-bicep/unit/test_persona_lake.py
  - environment_setup/unit-tests/test-bicep/unit/test_registered_personas.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_enrollment.py
  - environment_setup/unit-tests/test-bicep/integration/test_persona_authorization.py
graph_symbols:
  - bootstrap/lib/registered_personas.py
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
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

Deployment identities, runtime managed identities, human principals and provider service connections serve different purposes. Application runtime inference/search grants do not imply permission to deploy agents, mutate infrastructure or retrieve arbitrary secrets.

## Intended constraints

Adoption requires the reviewed manifest and matching scripts/pipelines. Merely placing new groups in old arrays is not migration. Effective access also depends on inherited Azure assignments, nested Entra membership, existing credentials, workload identities and service-specific data permissions.

Offline policy tests establish contract behavior; the cited opt-in live authorization test is not evidence of a live run in this vault task. Preserve security groups through deletion paths that explicitly require it.

See [[Factory-Scope-Model]], [[IaC-and-Private-Networking]], [[Trust-and-Authorization]], [[Lake-and-Data-Lineage]] and [[Index]].

Authority: [persona walkthrough](../../../environment_setup/aifactory/bicep/personas/readme.md), [release clarification](../../../RELEASE_125.md).
