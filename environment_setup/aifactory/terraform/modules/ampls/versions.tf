terraform {
  required_version = ">= 1.11.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = ">= 5.12.0, < 6.0.0" }
    azapi   = { source = "azure/azapi", version = ">= 2.13.0, < 3.0.0" }
  }
}
