terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# Base resource group
resource "azurerm_resource_group" "rg" {
  name     = "rg-showcase-sandbox"
  location = "West Europe"
}

# Frontend hosting
resource "azurerm_static_web_app" "frontend" {
  name                = "stapp-showcase-frontend"
  resource_group_name = azurerm_resource_group.rg.name
  location            = "West Europe"
  sku_tier            = "Free"
  sku_size            = "Free"
}

# Unique suffix for storage account
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Storage for backend functions
resource "azurerm_storage_account" "function_storage" {
  name                     = "stshowcasefunc${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

# Consumption plan (serverless)
resource "azurerm_service_plan" "function_plan" {
  name                = "plan-showcase-functions"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "Y1"
}

# Backend functions (Budget guard & orchestration)
resource "azurerm_linux_function_app" "backend" {
  name                       = "func-showcase-backend"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  service_plan_id            = azurerm_service_plan.function_plan.id
  storage_account_name       = azurerm_storage_account.function_storage.name
  storage_account_access_key = azurerm_storage_account.function_storage.primary_access_key

  site_config {
    application_stack {
      python_version = "3.9"
    }
  }
}

# Managed identity for OIDC/WIF
resource "azurerm_user_assigned_identity" "sandbox_identity" {
  name                = "id-showcase-sandbox"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}