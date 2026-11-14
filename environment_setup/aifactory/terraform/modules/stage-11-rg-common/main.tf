# Port of environment_setup/aifactory/bicep/esml-common/main/11-rgCommon.bicep (targetScope subscription).
# Every module call below is a Bicep `module` of the same symbol; its `if` is local.deploy.<symbol>.

locals {
  p   = var.parameters
  sub = var.subscription_id

  personas_groups_enabled = try(local.p.tags["AIF-Persona-Access"], "") == "groups-v1"
  # Same body as normalizedObjectIds in modules/common/objectIds.bicep.
  technical_admins_object_ids = local.personas_groups_enabled ? [] : distinct([
    for id in split(",", local.p.technicalAdminsObjectID) : lower(trimspace(id))
    if lower(trimspace(id)) != "" && lower(trimspace(id)) != "null"
  ])
  technical_admins_emails = (local.personas_groups_enabled || local.p.technicalAdminsEmail == "" || local.p.technicalAdminsEmail == "null") ? [] : split(",", local.p.technicalAdminsEmail)

  common_resource_group_name = module.naming.common_resource_group_name
  cmk_identity_name          = module.naming.names.cmkIdentityName

  deploy = {
    rgCommon                = true
    contributorPermissions  = true
    vmAdminLoginPermissions = local.p.enableAdminVM
    cmkIdentity             = local.p.cmk
    defenderForCloud        = local.p.enableDefenderforAISubLevel
  }
}

module "naming" {
  source                      = "../naming"
  subscription_id             = local.sub
  env                         = local.p.env
  location                    = local.p.location
  location_suffix             = local.p.locationSuffix
  aifactory_suffix_rg         = local.p.aifactorySuffixRG
  common_rg_name_prefix       = local.p.commonRGNamePrefix
  common_resource_name        = local.p.esmlCommonOverride
  common_resource_suffix      = local.p.commonResourceSuffix
  common_resource_group_param = local.p.commonResourceGroup_param
  vnet_name_base              = ""
}

module "rgCommon" {
  source   = "../resource-group-unmanaged"
  rg_name  = local.common_resource_group_name
  location = local.p.location
  tags     = local.p.tags
}

module "contributorPermissions" {
  source                 = "../contributor-rbac"
  subscription_id        = local.sub
  resource_group_name    = local.common_resource_group_name
  user_email             = local.personas_groups_enabled ? "" : local.p.technicalContactEmail
  additional_user_ids    = local.technical_admins_object_ids
  additional_user_emails = local.technical_admins_emails
  use_ad_groups          = local.p.useAdGroups

  depends_on = [module.rgCommon]
}

module "vmAdminLoginPermissions" {
  source                 = "../vm-admin-login-rbac"
  count                  = local.deploy.vmAdminLoginPermissions ? 1 : 0
  subscription_id        = local.sub
  resource_group_name    = local.common_resource_group_name
  user_email             = local.personas_groups_enabled ? "" : local.p.technicalContactEmail
  additional_user_ids    = local.technical_admins_object_ids
  additional_user_emails = local.technical_admins_emails
  use_ad_groups          = local.p.useAdGroups

  depends_on = [module.rgCommon]
}

# CMK UAMI creation (before 13-rgLevel, so it has propagated when 13 grants it Key Vault access)
module "cmkIdentity" {
  source              = "../managed-identity"
  count               = local.deploy.cmkIdentity ? 1 : 0
  subscription_id     = local.sub
  resource_group_name = local.common_resource_group_name
  name                = local.cmk_identity_name
  location            = local.p.location
  tags                = local.p.tags

  depends_on = [module.rgCommon]
}

# Microsoft Defender for Cloud at subscription level
module "defenderForCloud" {
  source                                  = "../defender"
  count                                   = local.deploy.defenderForCloud ? 1 : 0
  subscription_id                         = local.sub
  enable_all                              = false
  pricing_tier                            = "Standard"
  advanced_pricing_tier                   = "Standard"
  enable_defender_for_ai                  = local.p.enableDefenderforAISubLevel
  enable_defender_for_key_vault           = true
  enable_defender_for_storage             = true
  enable_defender_for_containers          = false
  enable_defender_for_cloud_posture       = false
  enable_defender_for_virtual_machines    = local.p.enableAdminVM
  vm_sub_plan                             = "P2"
  enforce                                 = "False"
  enable_ai_prompt_evidence               = false
  enable_storage_malware_scanning         = true
  enable_storage_sensitive_data_discovery = true

  depends_on = [module.rgCommon]
}
