# System Design & Architecture

## 1. High-Level Architecture
The system follows an **Ephemeral Infrastructure** pattern.
`[GitHub Actions]` -> `[Terraform]` -> `[Azure Cloud]` -> `[Python Verification]`

## 2. Detailed Workflow

### Phase 1: The Trigger & Setup
- **Actor:** GitHub Actions Scheduler.
- **Action:** checkouts code and logs into Azure using a Service Principal (OIDC/Client Secret).
- **Environment:** Ubuntu-latest runner (pre-installed with Terraform & Python).

### Phase 2: Infrastructure as Code (Terraform)
- **Action:** `terraform apply`
- **Resources Created:**
  1.  **Resource Group:** `rg-phoenix-drill-{run_id}` (Isolated container).
  2.  **SQL Server (Logical):** `sql-phoenix-{run_id}`.
  3.  **Firewall Rule:** `AllowAzureServices` (Enables the GitHub Runner and Azure management plane to talk to the SQL Server).
- **Output:** Terraform exports the `sql_server_fqdn` (Fully Qualified Domain Name) and `resource_group_name` for the Python script.

### Phase 3: The "Phoenix" Logic (Python)
- **Script:** `drill_master.py`
- **Step A (Identify):** Use `azure-mgmt-sql` to find the *Source* Database (Production) and get its latest `earliestRestoreDate`.
- **Step B (Restore):** Trigger a `CreateMode=Restore` operation.
    - *Crucial Design Note:* We do not create an empty DB in Terraform. We let the Azure API create the DB *during* the restore process onto the SQL Server created in Phase 2.
- **Step C (Verify):**
    - Connect via `pyodbc` (ODBC Driver 18).
    - Run query: `SELECT COUNT(*) FROM dbo.Users;`
    - Assert: `Count >= Expected_Threshold`.

### Phase 4: The Cleanup (Terraform)
- **Action:** `terraform destroy -auto-approve`
- **Condition:** Runs `if: always()` (even if the Python script crashes) to guarantee cost control.

## 3. Data Flow Diagram
1. **Prod DB (Backup Vault)** --(Restore API)--> **Drill SQL Server**
2. **Python Script** --(SQL Query)--> **Drill SQL Server**
3. **Terraform** --(Delete API)--> **Drill Resource Group**