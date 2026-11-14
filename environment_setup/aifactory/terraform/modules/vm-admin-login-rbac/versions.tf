terraform {
  required_version = ">= 1.11.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = ">= 5.12.0, < 6.0.0" }
  }
}
