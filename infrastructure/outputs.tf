# ============================================================
# Phoenix Protocol — Terraform Outputs
# These values are captured by the GitHub Actions workflow
# and passed as environment variables to drill_master.py.
# ============================================================

output "sql_server_fqdn" {
  description = "Fully Qualified Domain Name of the drill SQL Server. Used by pyodbc to establish a connection."
  value       = azurerm_mssql_server.drill.fully_qualified_domain_name
}

output "resource_group_name" {
  description = "Name of the ephemeral drill Resource Group. Used by drill_master.py to scope Azure SDK calls."
  value       = azurerm_resource_group.drill.name
}

output "drill_sql_server_name" {
  description = "Short name of the drill SQL Server. Used by azure-mgmt-sql to target the restore operation."
  value       = azurerm_mssql_server.drill.name
}
