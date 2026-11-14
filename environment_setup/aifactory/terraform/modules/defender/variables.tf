variable "subscription_id" {
  description = "Subscription whose Defender for Cloud plans are configured (the Bicep module's subscription scope)."
  type        = string
}

variable "enable_all" {
  description = "Explicitly manage all six plans implemented by this module, overriding individual flags. False respects individual flags; disable every flag to leave every plan unmanaged. This is not a complete subscription compliance baseline."
  type        = bool
  default     = false
}

variable "pricing_tier" {
  description = "Pricing tier for AI and Key Vault. Free explicitly disables paid protection; Standard can incur subscription-wide charges."
  type        = string
  default     = "Standard"
  validation {
    condition     = contains(["Standard", "Free"], var.pricing_tier)
    error_message = "pricing_tier must be one of: Standard, Free."
  }
}

variable "advanced_pricing_tier" {
  description = "Pricing tier for Storage, Containers, Cloud Posture, and Virtual Machines plans."
  type        = string
  default     = "Standard"
  validation {
    condition     = contains(["Standard", "Free"], var.advanced_pricing_tier)
    error_message = "advanced_pricing_tier must be one of: Standard, Free."
  }
}

variable "enable_defender_for_ai" {
  description = "Optional. Enable Microsoft Defender for AI."
  type        = bool
  default     = true
}

variable "enable_defender_for_key_vault" {
  description = "Optional. Enable Defender for Key Vault."
  type        = bool
  default     = true
}

variable "enable_defender_for_storage" {
  description = "Optional. Enable Defender for Storage."
  type        = bool
  default     = true
}

variable "ai_plan_name" {
  description = "AI plan name."
  type        = string
  default     = "AI"
}

variable "enforce" {
  description = "If set to True, prevents overrides and forces this pricing configuration on all descendants."
  type        = string
  default     = "False"
  validation {
    condition     = contains(["True", "False"], var.enforce)
    error_message = "enforce must be one of: True, False."
  }
}

variable "ai_sub_plan" {
  description = "Optional sub-plan for AI pricing (when applicable)."
  type        = string
  default     = ""
}

variable "enable_ai_prompt_evidence" {
  description = "Enable AIPromptEvidence extension for AI plan."
  type        = bool
  default     = false
}

variable "storage_cap_gb_per_month_per_storage_account" {
  description = "Storage scanning capacity limit (GB per month per storage account)."
  type        = string
  default     = "5000"
}

variable "enable_storage_malware_scanning" {
  description = "Enable OnUploadMalwareScanning extension for Storage."
  type        = bool
  default     = true
}

variable "enable_storage_sensitive_data_discovery" {
  description = "Enable SensitiveDataDiscovery extension for Storage."
  type        = bool
  default     = true
}

variable "enable_defender_for_containers" {
  description = "Optional. Enable Defender for Containers."
  type        = bool
  default     = false
}

variable "enable_container_registries_vulnerability_assessments" {
  description = "Enable ContainerRegistriesVulnerabilityAssessments extension for Containers/CloudPosture."
  type        = bool
  default     = false
}

variable "enable_container_sensor" {
  description = "Enable ContainerSensor extension for Containers plan."
  type        = bool
  default     = false
}

variable "enable_agentless_discovery_for_kubernetes" {
  description = "Enable AgentlessDiscoveryForKubernetes extension for Containers/CloudPosture."
  type        = bool
  default     = false
}

variable "enable_defender_for_cloud_posture" {
  description = "Optional. Enable Defender for Cloud Posture Management."
  type        = bool
  default     = false
}

variable "enable_defender_for_virtual_machines" {
  description = "Optional. Enable Defender for Virtual Machines."
  type        = bool
  default     = false
}

variable "vm_sub_plan" {
  description = "Sub-plan for Virtual Machines (P1 or P2)."
  type        = string
  default     = "P2"
  validation {
    condition     = contains(["P1", "P2", ""], var.vm_sub_plan)
    error_message = "vm_sub_plan must be one of: P1, P2, ''."
  }
}

variable "enable_mde_designated_subscription" {
  description = "Enable MdeDesignatedSubscription extension for VirtualMachines plan."
  type        = bool
  default     = false
}
