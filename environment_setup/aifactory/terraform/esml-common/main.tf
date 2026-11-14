# AI Factory common foundation: one Terraform root for the three Bicep entry files of
# environment_setup/aifactory/bicep/esml-common/main, in the order infra-common.yml runs them.
# One root (not three) because all three deploy at subscription scope into the same subscription, and
# Terraform orders them through module dependencies in one plan and one state per factory and environment.

module "scopes" {
  source          = "../modules/common-scopes"
  parameters      = local.p13
  subscription_id = local.subscription_id
}

# 01_az_bicep_common_rg -> 11-rgCommon.bicep
module "stage_11" {
  source          = "../modules/stage-11-rg-common"
  parameters      = local.p11
  subscription_id = local.subscription_id
}

# 02_az_bicep_private_networking -> 12-networkCommon.bicep
# (the workflow step runs when runNetworkingVar != 'false' and BYO_subnets != 'true')
module "stage_12" {
  source          = "../modules/stage-12-network-common"
  count           = local.run_networking ? 1 : 0
  parameters      = local.p12
  subscription_id = local.subscription_id

  depends_on = [module.stage_11]
}

# 03_az_bicep_deploy_resources -> 13-rgLevel.bicep
module "stage_13" {
  source                  = "../modules/stage-13-rg-level"
  parameters              = local.p13
  subscription_id         = local.subscription_id
  admin_password          = var.admin_password
  key_vault_secret_expiry = var.key_vault_secret_expiry
  cmk_identity            = module.stage_11.cmk_identity
  common_sp_oid           = try(data.azurerm_key_vault_secret.common_sp_oid[0].value, "")
  common_sp_id_secret     = try(ephemeral.azurerm_key_vault_secret.common_sp["id"].value, null)
  common_sp_secret_value  = try(ephemeral.azurerm_key_vault_secret.common_sp["secret"].value, null)
  common_sp_oid_secret    = try(ephemeral.azurerm_key_vault_secret.common_sp["oid"].value, null)

  providers = {
    azurerm             = azurerm
    azurerm.private_dns = azurerm.private_dns
    azurerm.own_hub     = azurerm.own_hub
  }

  depends_on = [module.stage_11, module.stage_12]
}

# externalKv.getSecret(...): the common service principal in the seeding Key Vault (inputKeyvault). The Bicep resolves
# getSecret inside ARM; Terraform reads the data plane, so the runner needs read access to that vault (Key Vault
# Secrets User, and its firewall must admit the runner). The object id is not a secret and drives role assignments;
# the three values copied into the common vault are ephemeral and never reach the plan or the state.
data "azurerm_key_vault_secret" "common_sp_oid" {
  count        = module.scopes.read_common_sp_oid ? 1 : 0
  name         = local.p13.commonServicePrincipleOIDKey
  key_vault_id = module.scopes.seeding_key_vault_id
}

ephemeral "azurerm_key_vault_secret" "common_sp" {
  for_each = module.scopes.copy_common_sp ? {
    id     = local.p13.inputCommonSPIDKey
    secret = local.p13.inputCommonSPSecretKey
    oid    = local.p13.commonServicePrincipleOIDKey
  } : {}
  name         = each.value
  key_vault_id = module.scopes.seeding_key_vault_id
}
