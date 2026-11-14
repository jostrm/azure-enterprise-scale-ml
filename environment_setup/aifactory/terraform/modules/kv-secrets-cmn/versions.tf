terraform {
  required_version = ">= 1.11.0"
  required_providers {
    azapi = { source = "azure/azapi", version = ">= 2.13.0, < 3.0.0" }
  }
}
