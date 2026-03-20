variable "run_id" {
  description = "Unique identifier for this drill run (injected from GitHub Actions run_id). Used to name ephemeral resources so they never collide across runs."
  type        = string
}

variable "location" {
  description = "Azure region where the drill environment will be provisioned."
  type        = string
  default     = "West US 2"
}

variable "sql_admin_username" {
  description = "Administrator login username for the drill SQL Server."
  type        = string
  default     = "phoenix-admin"
}

variable "sql_admin_password" {
  description = "Administrator login password for the drill SQL Server. Injected from GitHub Secret SQL_ADMIN_PASSWORD. Never hardcode this value."
  type        = string
  sensitive   = true
}
