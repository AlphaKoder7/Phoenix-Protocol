# ============================================================
# Phoenix Protocol — Drill Environment
# Ephemeral resources created per run and destroyed after.
# NOTE: No azurerm_mssql_database is defined here.
#       The Python script (drill_master.py) creates the database
#       implicitly via a CreateMode=PointInTimeRestore API call.
# ============================================================

# ----------------------------------------------------------
# 1. Resource Group
#    Isolated container for all drill resources.
#    Named with run_id to guarantee uniqueness per pipeline run.
# ----------------------------------------------------------
resource "azurerm_resource_group" "drill" {
  name     = "rg-phoenix-drill-${var.run_id}"
  location = var.location
}

# ----------------------------------------------------------
# 2. SQL Server (Logical)
#    The target server onto which the production DB is restored.
#    version = "12.0" is the current Azure SQL logical server version.
# ----------------------------------------------------------
resource "azurerm_mssql_server" "drill" {
  name                         = "sql-phoenix-${var.run_id}"
  resource_group_name          = azurerm_resource_group.drill.name
  location                     = azurerm_resource_group.drill.location
  version                      = "12.0"
  administrator_login          = var.sql_admin_username
  administrator_login_password = var.sql_admin_password
}

# ----------------------------------------------------------
# 3. Firewall Rule — Allow Azure Services
#    start_ip = end_ip = "0.0.0.0" is the Azure convention that
#    enables the GitHub Actions runner (an Azure-hosted IP) and
#    the Azure management plane to reach this SQL Server.
# ----------------------------------------------------------
resource "azurerm_mssql_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.drill.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
