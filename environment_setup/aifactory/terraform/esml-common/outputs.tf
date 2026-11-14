output "parameters" {
  description = "The parameters of each stage, keyed by Bicep entry file and Bicep parameter name (secrets excluded)."
  value = {
    "11-rgCommon"      = local.p11
    "12-networkCommon" = local.p12
    "13-rgLevel"       = local.p13
  }
}

output "run_networking" {
  description = "Whether 12-networkCommon runs (the workflow's 02 step condition)."
  value       = local.run_networking
}

output "deploy" {
  description = "Bicep module/resource symbol -> deployed?, per entry file: the conditions every count uses."
  value = {
    "11-rgCommon"      = module.stage_11.deploy
    "12-networkCommon" = try(module.stage_12[0].deploy, {})
    "13-rgLevel"       = module.stage_13.deploy
  }
}

output "names" {
  description = "Names of the common resources (the Bicep naming convention, modules/naming)."
  value = {
    "11-rgCommon"      = module.stage_11.names
    "12-networkCommon" = try(module.stage_12[0].names, {})
    "13-rgLevel"       = module.stage_13.names
  }
}

output "adminVmResourceId" {
  description = "Admin VM resource ID. Empty when enableAdminVM is false or only AI Gateway networking is deployed."
  value       = module.stage_13.adminVmResourceId
}

output "adminVmName" {
  description = "Admin VM name and recommended self-hosted agent name. Empty when the admin VM is disabled."
  value       = module.stage_13.adminVmName
}
