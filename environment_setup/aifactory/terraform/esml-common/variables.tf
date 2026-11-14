# Inputs. Everything a Bicep deployment of 11/12/13 takes from variables.json is read from that same file
# (config.tf); these variables carry only what the Bicep workflow takes from GitHub secrets, GitHub
# variables or its own steps (infra-common.yml), plus the file and environment to read.

variable "config_file" {
  description = "Path to the AI Factory variables.json (the file infra-common.yml reads with use_json_config_override)."
  type        = string
}

variable "environment" {
  description = "dev, test or prod (the Bicep dev_test_prod; the GitHub Stage job deploys test)."
  type        = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "subscription_id" {
  description = "Target subscription (GitHub variable AZURE_SUBSCRIPTION_ID). Empty: <env>_sub_id from the config file."
  type        = string
  default     = ""
}

variable "tenant_id" {
  description = "GitHub secret TENANT_ID. The config file's tenantId wins when present, as in the Bicep workflow."
  type        = string
  default     = ""
}

variable "seeding_keyvault_subscription_id" {
  description = "GitHub secret AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID. Empty: <env>_admin_bicep_input_keyvault_subscription from the config file."
  type        = string
  default     = ""
}

variable "seeding_keyvault_name" {
  description = "GitHub variable AIFACTORY_SEEDING_KEYVAULT_NAME. Empty: <env>_admin_bicep_kv_fw from the config file."
  type        = string
  default     = ""
}

variable "seeding_keyvault_resource_group" {
  description = "GitHub variable AIFACTORY_SEEDING_KEYVAULT_RG. Empty: <env>_admin_bicep_kv_fw_rg from the config file."
  type        = string
  default     = ""
}

variable "cidr_range" {
  description = "GitHub variable CIDR_RANGE (replaces XX in the CIDRs). Empty: <env>_cidr_range from the config file."
  type        = string
  default     = ""
}

variable "network_env" {
  description = "Network environment, computed like the Bicep workflow step 'Initialize derived variables' (<ENV>_NETWORK_ENV, NETWORK_ENV, else the environment)."
  type        = string
  default     = ""
}

variable "technical_admins_ad_object_id" {
  description = "GitHub secret PROJECT_MEMBERS. The config file's technical_admins_ad_object_id wins when present."
  type        = string
  default     = ""
}

variable "technical_admins_email" {
  description = "GitHub variable PROJECT_MEMBERS_EMAILS. The config file's technical_admins_email wins when present."
  type        = string
  default     = ""
}

variable "ip_whitelist" {
  description = "GitHub secret PROJECT_MEMBERS_IP_ADDRESS ('-' means none)."
  type        = string
  default     = ""
}

variable "admin_vm_exists" {
  description = "Output of bicep/scripts/admin-vm-exists.sh: an existing admin VM is never PUT again."
  type        = bool
  default     = false
}

variable "admin_password" {
  description = "Local admin password of the admin VM (the Bicep workflow generates one per run)."
  type        = string
  sensitive   = true
  default     = null
}

variable "key_vault_secret_expiry" {
  description = "Expiry of every secret this deployment writes, in Unix epoch seconds (Bicep default: utcNow() + 1 year)."
  type        = number
}
