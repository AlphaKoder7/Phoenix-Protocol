# Technology Stack

## 1. Core Infrastructure (Azure)
- **Cloud Provider:** Microsoft Azure (Student Subscription).
- **Region:** East US (Cost-effective).
- **Target Resource:** Azure SQL Database (DTU Model: Basic Tier - 5 DTU).
- **Identity:** Azure AD Service Principal (App Registration) for CI/CD authentication.

## 2. Infrastructure as Code (IaC)
- **Tool:** Terraform (OpenTofu compatible).
- **Provider:** `hashicorp/azurerm` (v3.0+).
- **State Management:** Local State (stored temporarily in GitHub Runner) or Azure Blob Storage (optional for advanced setup).

## 3. Automation Logic
- **Language:** Python 3.10+
- **SDKs & Libraries:**
    - `azure-identity`: For authentication.
    - `azure-mgmt-sql`: To manage SQL Servers and trigger Restores.
    - `azure-mgmt-resource`: To lookup Resource Groups.
    - `pyodbc`: For executing SQL queries against the DB.
- **System Drivers:** `msodbcsql18` (ODBC Driver 18 for SQL Server) - *Required on the runner.*

## 4. CI/CD Pipeline
- **Platform:** GitHub Actions.
- **Runner OS:** `ubuntu-latest`.
- **Secrets Management:** GitHub Repository Secrets (`AZURE_CLIENT_ID`, `SQL_ADMIN_PASSWORD`, `SUBSCRIPTION_ID`).