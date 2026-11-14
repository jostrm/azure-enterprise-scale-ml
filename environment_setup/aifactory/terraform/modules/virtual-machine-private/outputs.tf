output "vm_resource_id" {
  description = "Private VM resource ID. Use this to identify a self-hosted build agent without deriving its name externally."
  value       = local.vm_resource_id
}

output "vm_name" {
  description = "Private VM name. Register self-hosted Azure DevOps agents with this exact name."
  value       = var.vm_name
}
