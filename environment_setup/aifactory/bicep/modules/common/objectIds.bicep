// Entra object ID lists such as technical_admins_ad_object_id: the one normalization rule. It accepts every value the
// preflight gate (scripts/kv_principal_object_ids.py) accepts, trimmed and in any case, and also tolerates empty or
// 'null' entries. Role-assignment names are seeded with the object ID, so spacing or case must not rename them
// (RoleAssignmentExists on redeploy).
// Importing a user-defined function compiles a template to ARM languageVersion 2.0, which changes how its 'existing'
// resources deploy. So only CmnAIfactoryNaming (already 2.0) imports it. The classic templates 11-rgCommon, 13-rgLevel
// and kvCmnAccessPolicys inline this exact body, as does esml-project/22-main, and unit/test_admin_object_ids.py pins
// every copy.

@export()
@description('Trimmed, lower-cased object IDs without duplicates, empty or \'null\' entries, in first-seen order.')
func normalizedObjectIds(ids array) array => union(filter(map(ids, id => toLower(trim(id))), id => !empty(id) && id != 'null'), [])
