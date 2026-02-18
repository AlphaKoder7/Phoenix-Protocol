terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

# Authentication is handled entirely via environment variables:
#   ARM_CLIENT_ID       = ${{ secrets.AZURE_CLIENT_ID }}
#   ARM_CLIENT_SECRET   = ${{ secrets.AZURE_CLIENT_SECRET }}
#   ARM_TENANT_ID       = ${{ secrets.AZURE_TENANT_ID }}
#   ARM_SUBSCRIPTION_ID = ${{ secrets.SUBSCRIPTION_ID }}
# No credentials are hardcoded here.
provider "azurerm" {
  features {}
}
