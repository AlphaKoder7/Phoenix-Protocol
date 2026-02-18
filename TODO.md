# Phoenix Protocol — Project TODO

> **Automated Disaster Recovery & Reliability Pipeline**
> Tasks are ordered by dependency. Complete each phase before starting the next.

---

## ✅ Phase 1: Project Setup & Prerequisites

### 1.1 Local Environment
- [ ] Install **Terraform CLI** (v1.5+) and verify with `terraform -version`
- [ ] Install **Python 3.10+** and verify with `python --version`
- [ ] Install **pip** dependencies globally or create a `venv`: `python -m venv .venv`
- [ ] Install required Python libraries:
  - [ ] `pip install azure-identity`
  - [ ] `pip install azure-mgmt-sql`
  - [ ] `pip install azure-mgmt-resource`
  - [ ] `pip install pyodbc`
- [ ] Create `requirements.txt` by running `pip freeze > requirements.txt`
- [ ] Install **ODBC Driver 18 for SQL Server** (`msodbcsql18`) on local machine for local testing

### 1.2 Azure Account & Service Principal
- [ ] Log into Azure Portal and confirm **Student Subscription** is active
- [ ] Register a new **App Registration** (Service Principal) in Azure AD:
  - [ ] Name it `sp-phoenix-protocol`
  - [ ] Note down `AZURE_CLIENT_ID` and `AZURE_TENANT_ID`
- [ ] Generate a **Client Secret** for the Service Principal and note it down
- [ ] Assign the Service Principal the **Contributor** role on the Subscription (needed for Terraform to create/destroy Resource Groups)
- [ ] Assign the Service Principal the **SQL Server Contributor** role (needed for `azure-mgmt-sql` restore operations)
- [ ] Identify the **Production Azure SQL Server** and **Production Database** name to be used as the restore source
- [ ] Note down the **Production Resource Group** name

### 1.3 GitHub Repository Setup
- [ ] Create a new GitHub repository: `phoenix-protocol`
- [ ] Initialize with a `.gitignore` (include `*.tfstate`, `*.tfstate.backup`, `.terraform/`, `.venv/`, `__pycache__/`)
- [ ] Add a `README.md` with a brief project description
- [ ] Navigate to **Settings → Secrets and Variables → Actions** and add the following secrets:
  - [ ] `AZURE_CLIENT_ID`
  - [ ] `AZURE_CLIENT_SECRET`
  - [ ] `AZURE_TENANT_ID`
  - [ ] `SUBSCRIPTION_ID`
  - [ ] `SQL_ADMIN_PASSWORD` (strong password for the drill SQL Server)
  - [ ] `PROD_SQL_SERVER_NAME` (name of the production SQL Server)
  - [ ] `PROD_DB_NAME` (name of the production database)
  - [ ] `PROD_RESOURCE_GROUP` (resource group of the production server)

### 1.4 Project Directory Structure
- [ ] Create the following folder structure in the repo:
  ```
  phoenix-protocol/
  ├── terraform/
  │   ├── main.tf
  │   ├── variables.tf
  │   ├── outputs.tf
  │   └── providers.tf
  ├── scripts/
  │   └── drill_master.py
  ├── .github/
  │   └── workflows/
  │       └── phoenix_drill.yml
  ├── requirements.txt
  └── README.md
  ```

---

## ✅ Phase 2: Terraform — Ephemeral Drill Infrastructure

> **Goal:** Define the IaC that creates and destroys the isolated "Drill Environment."
> All files live in the `terraform/` directory.

### 2.1 `providers.tf` — Configure the AzureRM Provider
- [ ] Define the `terraform` block with required provider `hashicorp/azurerm` version `~> 3.0`
- [ ] Define the `provider "azurerm"` block with `features {}` block
- [ ] Configure authentication via environment variables (`ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID`) — **no hardcoded credentials**

### 2.2 `variables.tf` — Declare Input Variables
- [ ] Declare variable `run_id` (type: `string`) — unique identifier per pipeline run (e.g., GitHub `run_id`)
- [ ] Declare variable `location` (type: `string`, default: `"East US"`)
- [ ] Declare variable `sql_admin_username` (type: `string`, default: `"phoenix-admin"`)
- [ ] Declare variable `sql_admin_password` (type: `string`, sensitive: `true`) — injected from GitHub Secret

### 2.3 `main.tf` — Define Azure Resources
- [ ] **Define Resource Group:**
  ```hcl
  resource "azurerm_resource_group" "drill" {
    name     = "rg-phoenix-drill-${var.run_id}"
    location = var.location
  }
  ```
- [ ] **Define SQL Server (Logical):**
  ```hcl
  resource "azurerm_mssql_server" "drill" {
    name                         = "sql-phoenix-${var.run_id}"
    resource_group_name          = azurerm_resource_group.drill.name
    location                     = azurerm_resource_group.drill.location
    version                      = "12.0"
    administrator_login          = var.sql_admin_username
    administrator_login_password = var.sql_admin_password
  }
  ```
- [ ] **Define Firewall Rule** to allow Azure Services:
  ```hcl
  resource "azurerm_mssql_firewall_rule" "allow_azure" {
    name             = "AllowAzureServices"
    server_id        = azurerm_mssql_server.drill.id
    start_ip_address = "0.0.0.0"
    end_ip_address   = "0.0.0.0"
  }
  ```
- [ ] **Do NOT** define an `azurerm_mssql_database` resource — the database is created by the Python restore API call (as per Design.md)

### 2.4 `outputs.tf` — Export Values for Python Script
- [ ] Output `sql_server_fqdn`:
  ```hcl
  output "sql_server_fqdn" {
    value = azurerm_mssql_server.drill.fully_qualified_domain_name
  }
  ```
- [ ] Output `resource_group_name`:
  ```hcl
  output "resource_group_name" {
    value = azurerm_resource_group.drill.name
  }
  ```
- [ ] Output `drill_sql_server_name`:
  ```hcl
  output "drill_sql_server_name" {
    value = azurerm_mssql_server.drill.name
  }
  ```

### 2.5 Terraform Validation (Local)
- [ ] Run `terraform init` inside `terraform/` directory — confirm provider download succeeds
- [ ] Run `terraform validate` — confirm no syntax errors
- [ ] Run `terraform plan -var="run_id=test001" -var="sql_admin_password=TestPass123!"` — review the plan output (3 resources to add)
- [ ] **Do NOT** run `terraform apply` locally yet (costs money); defer to CI/CD

---

## ✅ Phase 3: Python Logic — `drill_master.py`

> **Goal:** Write the "Phoenix" logic that identifies, restores, verifies, and reports.
> File lives at `scripts/drill_master.py`.
> **Prerequisite:** Phase 2 Terraform outputs must be defined first.

### 3.1 Script Setup & Configuration
- [ ] Import required libraries: `os`, `time`, `sys`, `json`
- [ ] Import `azure.identity.ClientSecretCredential` from `azure-identity`
- [ ] Import `SqlManagementClient` from `azure-mgmt-sql`
- [ ] Import `pyodbc`
- [ ] Read all configuration from **environment variables** (never hardcode):
  - [ ] `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `SUBSCRIPTION_ID`
  - [ ] `PROD_SQL_SERVER_NAME`, `PROD_DB_NAME`, `PROD_RESOURCE_GROUP`
  - [ ] `DRILL_SQL_SERVER_NAME` (from Terraform output)
  - [ ] `DRILL_RESOURCE_GROUP` (from Terraform output)
  - [ ] `SQL_ADMIN_USERNAME`, `SQL_ADMIN_PASSWORD`
  - [ ] `DRILL_SQL_SERVER_FQDN` (from Terraform output)

### 3.2 Step A — Authenticate to Azure
- [ ] Instantiate `ClientSecretCredential` using `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
- [ ] Instantiate `SqlManagementClient(credential, SUBSCRIPTION_ID)`
- [ ] Add a print statement confirming successful authentication

### 3.3 Step B — Identify the Latest Restore Point
- [ ] Call `sql_client.restore_points.list_by_database(PROD_RESOURCE_GROUP, PROD_SQL_SERVER_NAME, PROD_DB_NAME)`
- [ ] Parse the response to find the **most recent** `earliest_restore_date`
- [ ] Print the identified restore point timestamp
- [ ] Handle the case where no restore points are found (raise a clear exception)

### 3.4 Step C — Trigger the Database Restore
- [ ] Build the restore parameters object using `CreateMode = "PointInTimeRestore"` (or `"Recovery"` depending on source type — verify against `azure-mgmt-sql` SDK docs)
- [ ] Set `source_database_id` to the full ARM resource ID of the Production database
- [ ] Set `restore_point_in_time` to the identified restore point
- [ ] Call `sql_client.databases.begin_create_or_update(DRILL_RESOURCE_GROUP, DRILL_SQL_SERVER_NAME, "phoenix-drill-db", parameters)`
- [ ] Use `.result()` to **block and wait** for the long-running restore operation to complete (this can take 5–15 minutes)
- [ ] Print confirmation when the restore operation succeeds

### 3.5 Step D — Verify Data Integrity via `pyodbc`
- [ ] Build the `pyodbc` connection string using:
  - Driver: `{ODBC Driver 18 for SQL Server}`
  - Server: `DRILL_SQL_SERVER_FQDN`
  - Database: `phoenix-drill-db`
  - UID/PWD: `SQL_ADMIN_USERNAME` / `SQL_ADMIN_PASSWORD`
  - `Encrypt=yes`, `TrustServerCertificate=no`, `Connection Timeout=30`
- [ ] Wrap the connection in a `try/except` block
- [ ] Execute query: `SELECT COUNT(*) FROM dbo.Users;`
- [ ] Read the result and store the row count
- [ ] Define `EXPECTED_THRESHOLD` (e.g., `1`) and assert `row_count >= EXPECTED_THRESHOLD`
- [ ] Print `[PASS] Data integrity verified. Row count: {count}` on success
- [ ] Print `[FAIL] Data integrity check failed. Row count: {count}` and `sys.exit(1)` on failure

### 3.6 Script Error Handling & Exit Codes
- [ ] Wrap the entire script in a `try/except/finally` block
- [ ] Ensure the script exits with code `0` on success and `1` on any failure
- [ ] Add meaningful print statements at each step for CI/CD log visibility

### 3.7 Local Testing (Dry Run)
- [ ] Test authentication step locally by running the script with only the auth section active
- [ ] Verify `azure-mgmt-sql` can list restore points from the production database
- [ ] Verify `pyodbc` can connect to a known SQL Server (use production read-only for connection test only)

---

## ✅ Phase 4: CI/CD Pipeline — GitHub Actions

> **Goal:** Wire everything together in a scheduled, fully automated workflow.
> File lives at `.github/workflows/phoenix_drill.yml`.
> **Prerequisite:** Phases 2 and 3 must be complete and tested.

### 4.1 Workflow Skeleton & Trigger
- [ ] Define `name: Phoenix Protocol - DR Drill`
- [ ] Define `on:` triggers:
  - [ ] `schedule:` with `cron: '0 2 * * 0'` (Every Sunday at 2 AM UTC)
  - [ ] `workflow_dispatch:` (for manual trigger during testing)

### 4.2 Job Definition
- [ ] Define job `phoenix-drill` running on `ubuntu-latest`
- [ ] Add `permissions: id-token: write` and `contents: read` (for OIDC, if used later)

### 4.3 Step — Checkout Code
- [ ] Add step: `uses: actions/checkout@v4`

### 4.4 Step — Install Terraform
- [ ] Add step: `uses: hashicorp/setup-terraform@v3` with `terraform_version: "1.5.x"`

### 4.5 Step — Set Up Python
- [ ] Add step: `uses: actions/setup-python@v5` with `python-version: '3.10'`

### 4.6 Step — Install ODBC Driver 18 (`msodbcsql18`)
- [ ] Add a `run:` step to install the ODBC driver on the Ubuntu runner:
  ```bash
  curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
  curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
  sudo apt-get update
  sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18
  ```

### 4.7 Step — Install Python Dependencies
- [ ] Add step: `run: pip install -r requirements.txt`

### 4.8 Step — Terraform Init & Apply
- [ ] Add step with `working-directory: ./terraform`
- [ ] Set environment variables: `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` from GitHub Secrets
- [ ] Run:
  ```bash
  terraform init
  terraform apply -auto-approve \
    -var="run_id=${{ github.run_id }}" \
    -var="sql_admin_password=${{ secrets.SQL_ADMIN_PASSWORD }}"
  ```
- [ ] Capture Terraform outputs into environment variables for the next step:
  ```bash
  echo "DRILL_SQL_SERVER_FQDN=$(terraform output -raw sql_server_fqdn)" >> $GITHUB_ENV
  echo "DRILL_SQL_SERVER_NAME=$(terraform output -raw drill_sql_server_name)" >> $GITHUB_ENV
  echo "DRILL_RESOURCE_GROUP=$(terraform output -raw resource_group_name)" >> $GITHUB_ENV
  ```

### 4.9 Step — Run Python Drill Script
- [ ] Add step: `run: python scripts/drill_master.py`
- [ ] Pass all required secrets and Terraform outputs as `env:` variables:
  - [ ] `AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}`
  - [ ] `AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}`
  - [ ] `AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}`
  - [ ] `SUBSCRIPTION_ID: ${{ secrets.SUBSCRIPTION_ID }}`
  - [ ] `SQL_ADMIN_PASSWORD: ${{ secrets.SQL_ADMIN_PASSWORD }}`
  - [ ] `PROD_SQL_SERVER_NAME: ${{ secrets.PROD_SQL_SERVER_NAME }}`
  - [ ] `PROD_DB_NAME: ${{ secrets.PROD_DB_NAME }}`
  - [ ] `PROD_RESOURCE_GROUP: ${{ secrets.PROD_RESOURCE_GROUP }}`
  - [ ] `DRILL_SQL_SERVER_FQDN: ${{ env.DRILL_SQL_SERVER_FQDN }}`
  - [ ] `DRILL_SQL_SERVER_NAME: ${{ env.DRILL_SQL_SERVER_NAME }}`
  - [ ] `DRILL_RESOURCE_GROUP: ${{ env.DRILL_RESOURCE_GROUP }}`

### 4.10 Step — Terraform Destroy (CRITICAL — Always Runs)
- [ ] Add step with `if: always()` — **this must run even if previous steps fail**
- [ ] Set `working-directory: ./terraform`
- [ ] Set the same `ARM_*` environment variables as the apply step
- [ ] Run:
  ```bash
  terraform destroy -auto-approve \
    -var="run_id=${{ github.run_id }}" \
    -var="sql_admin_password=${{ secrets.SQL_ADMIN_PASSWORD }}"
  ```
- [ ] Verify in Azure Portal after first run that the `rg-phoenix-drill-*` resource group is **deleted**

### 4.11 End-to-End Testing
- [ ] Trigger the workflow manually via `workflow_dispatch`
- [ ] Monitor the Actions run log for each step
- [ ] Confirm the drill SQL Server is created in Azure Portal during the run
- [ ] Confirm the restore operation completes and the Python script prints `[PASS]`
- [ ] Confirm the resource group is deleted after the run (zero zombie resources)
- [ ] Confirm total run time is **< 20 minutes** (NFR from PRD)
- [ ] Confirm cost per run is **< $0.05 USD** (check Azure Cost Analysis)

---

## 🔮 Future Scope (Post-MVP)

- [ ] Switch Terraform state backend from local to **Azure Blob Storage** for persistence
- [ ] Add **Email/Slack notification** step on Pass/Fail using a webhook secret
- [ ] Parameterize the verification query (`SELECT COUNT(*) FROM dbo.Users`) via a config file
- [ ] Add support for multiple databases in a single drill run
- [ ] Implement **OIDC-based authentication** (Federated Identity) to eliminate the `AZURE_CLIENT_SECRET`
- [ ] Add a Terraform `tags` block to all resources for cost tracking

---

*Generated by Senior DevOps Analysis of PRD.md, Design.md, and TechStack.md — Phoenix Protocol v1.0*
