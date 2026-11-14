output "role_assignment_count" {
  value = length(local.guid_principals) + (var.principal_is_managed_identity ? 1 : 0)
}
