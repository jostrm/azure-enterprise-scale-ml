terraform {
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.12.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "2.13.0"
    }
  }

  # Remote state in an Azure Storage container. The workflow passes the account, container and the key
  # "<factory>/<scale set>/<environment>/esml-common.tfstate" with -backend-config: one state per factory and
  # environment, never in the repository. Tests run `terraform init -backend=false`.
  backend "azurerm" {}
}
