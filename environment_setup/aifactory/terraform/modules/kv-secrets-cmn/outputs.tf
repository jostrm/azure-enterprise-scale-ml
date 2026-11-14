output "secret_names" {
  value = [var.esml_common_sp_id, var.esml_common_sp_oid, var.esml_common_sp_secret, var.esml_tenant_id, var.esml_subscription_id]
}
