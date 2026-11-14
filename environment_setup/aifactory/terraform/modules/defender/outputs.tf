output "defender_for_ai_enabled" {
  description = "Defender for AI enabled."
  value       = var.enable_all || var.enable_defender_for_ai
}

output "defender_for_storage_enabled" {
  description = "Defender for Storage enabled."
  value       = var.enable_all || var.enable_defender_for_storage
}

output "defender_for_key_vault_enabled" {
  description = "Defender for Key Vault enabled."
  value       = var.enable_all || var.enable_defender_for_key_vault
}

output "ai_prompt_evidence_enabled" {
  description = "AI Prompt Evidence extension enabled."
  value       = (var.enable_all || var.enable_defender_for_ai) && var.pricing_tier == "Standard" && var.enable_ai_prompt_evidence
}

output "storage_malware_scanning_enabled" {
  description = "Storage Malware Scanning extension enabled."
  value       = var.enable_storage_malware_scanning
}

output "storage_sensitive_data_discovery_enabled" {
  description = "Storage Sensitive Data Discovery extension enabled."
  value       = var.enable_storage_sensitive_data_discovery
}

output "defender_for_containers_enabled" {
  description = "Defender for Containers enabled."
  value       = var.enable_all || var.enable_defender_for_containers
}

output "container_registries_vulnerability_assessments_enabled" {
  description = "Container Registries Vulnerability Assessments extension enabled."
  value       = var.enable_container_registries_vulnerability_assessments
}

output "container_sensor_enabled" {
  description = "Container Sensor extension enabled."
  value       = var.enable_container_sensor
}

output "agentless_discovery_for_kubernetes_enabled" {
  description = "Agentless Discovery For Kubernetes extension enabled."
  value       = var.enable_agentless_discovery_for_kubernetes
}

output "defender_for_cloud_posture_enabled" {
  description = "Defender for Cloud Posture enabled."
  value       = var.enable_all || var.enable_defender_for_cloud_posture
}

output "defender_for_virtual_machines_enabled" {
  description = "Defender for Virtual Machines enabled."
  value       = var.enable_all || var.enable_defender_for_virtual_machines
}

output "mde_designated_subscription_enabled" {
  description = "MDE Designated Subscription extension enabled."
  value       = var.enable_mde_designated_subscription
}
