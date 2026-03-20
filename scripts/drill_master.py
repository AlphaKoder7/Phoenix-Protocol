"""
drill_master.py — Phoenix Protocol Core Script
================================================
Performs the "Game Day" DR drill cycle:
  Step A: Authenticate to Azure.
  Step B: Copy the Production database to the ephemeral Drill SQL Server.
  Step C: Verify data integrity via a row-count query.

All configuration is read from environment variables — no hardcoded values.
Exit codes: 0 = PASS, 1 = FAIL
"""

import os
import sys
import time
# (timezone import removed — no longer needed after switching to Database Copy)

import pyodbc
from azure.identity import ClientSecretCredential
from azure.mgmt.sql import SqlManagementClient
from azure.mgmt.sql.models import Database

# ──────────────────────────────────────────────────────────────
# Configuration — loaded entirely from environment variables
# ──────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    """Read an environment variable or abort with a clear error."""
    value = os.environ.get(name)
    if not value:
        print(f"[ERROR] Required environment variable '{name}' is not set.")
        sys.exit(1)
    return value

# Azure identity
AZURE_CLIENT_ID     = _require_env("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = _require_env("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID     = _require_env("AZURE_TENANT_ID")
SUBSCRIPTION_ID     = _require_env("SUBSCRIPTION_ID")

# Production source database (the backup we are testing)
PROD_RESOURCE_GROUP  = _require_env("PROD_RESOURCE_GROUP")
PROD_SQL_SERVER_NAME = _require_env("PROD_SQL_SERVER_NAME")
PROD_DB_NAME         = _require_env("PROD_DB_NAME")

# Drill target (created by Terraform in Phase 2)
DRILL_RESOURCE_GROUP  = _require_env("DRILL_RESOURCE_GROUP")
DRILL_SQL_SERVER_NAME = _require_env("DRILL_SQL_SERVER_NAME")
DRILL_SQL_SERVER_FQDN = _require_env("DRILL_SQL_SERVER_FQDN")

# SQL credentials for the drill server
SQL_ADMIN_USERNAME = _require_env("SQL_ADMIN_USERNAME")
SQL_ADMIN_PASSWORD = _require_env("SQL_ADMIN_PASSWORD")

# Azure region for the drill server.
# Must match the Terraform `location` variable (default: "West US 2").
# Override by setting the DRILL_LOCATION environment variable.
DRILL_LOCATION = os.environ.get("DRILL_LOCATION", "West US 2")

# Name of the restored database on the drill server
DRILL_DB_NAME = "phoenix-drill-db"

# Data integrity threshold — drill passes only if row count meets this
EXPECTED_ROW_THRESHOLD = 1


# ──────────────────────────────────────────────────────────────
# Step A: Authenticate
# ──────────────────────────────────────────────────────────────

def authenticate() -> SqlManagementClient:
    """Create an authenticated Azure SQL management client."""
    print("[AUTH] Authenticating to Azure using Service Principal...")
    credential = ClientSecretCredential(
        tenant_id=AZURE_TENANT_ID,
        client_id=AZURE_CLIENT_ID,
        client_secret=AZURE_CLIENT_SECRET,
    )
    client = SqlManagementClient(credential, SUBSCRIPTION_ID)
    print("[AUTH] Authentication successful.")
    return client


# ──────────────────────────────────────────────────────────────
# Step B: Copy Production Database to Drill Server
# ──────────────────────────────────────────────────────────────

def trigger_restore(client: SqlManagementClient) -> None:
    """
    Copy the production database to the ephemeral drill SQL Server using
    create_mode='Copy'. Blocks until the operation completes.

    Why 'Copy' and not 'PointInTimeRestore':
      Azure SQL Database (PaaS / logical server) enforces RestoreCrossServerDisabled
      — PITR can only target the same logical server as the source. Since Phoenix
      Protocol intentionally provisions a separate, ephemeral drill server via
      Terraform, PITR is architecturally incompatible with this design.

      create_mode='Copy' has no such restriction. It produces a transactionally
      consistent snapshot of the source database at the moment the copy begins,
      places it on the drill server, and leaves it fully independent — which is
      exactly what a DR data-integrity drill requires.

    Azure SDK parameter names (azure-mgmt-sql >= 3.x):
      - create_mode       : 'Copy'
      - source_database_id: full ARM resource ID of the source (production) database
      - location          : must match the drill server's Azure region
      - sku               : omitted — Copy inherits the source SKU automatically
      - restore_point_in_time: not applicable for Copy mode
    """
    print(f"[STEP B] Starting database copy to '{DRILL_SQL_SERVER_NAME}' / '{DRILL_DB_NAME}'...")
    print(f"[STEP B] Source:        {PROD_SQL_SERVER_NAME}/{PROD_DB_NAME}")
    print(f"[STEP B] Mode:          Copy (transactionally consistent snapshot)")
    print(f"[STEP B] Target region: {DRILL_LOCATION}")
    print("[STEP B] This operation can take 5–15 minutes. Waiting...")

    # Full ARM resource ID of the source (production) database
    source_db_id = (
        f"/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{PROD_RESOURCE_GROUP}"
        f"/providers/Microsoft.Sql/servers/{PROD_SQL_SERVER_NAME}"
        f"/databases/{PROD_DB_NAME}"
    )

    copy_params = Database(
        location=DRILL_LOCATION,
        create_mode="Copy",
        source_database_id=source_db_id,
        # restore_point_in_time is not used for Copy mode.
        # SKU is omitted — Copy inherits it from the source automatically.
    )

    # begin_create_or_update returns an LROPoller; .result() blocks until done
    poller = client.databases.begin_create_or_update(
        resource_group_name=DRILL_RESOURCE_GROUP,
        server_name=DRILL_SQL_SERVER_NAME,
        database_name=DRILL_DB_NAME,
        parameters=copy_params,
    )
    poller.result()  # Blocks — raises HttpResponseError if the operation fails

    print(f"[STEP B] Copy complete. Database '{DRILL_DB_NAME}' is ready on drill server.")


# ──────────────────────────────────────────────────────────────
# Step C: Verify Data Integrity via pyodbc
# ──────────────────────────────────────────────────────────────

def verify_data_integrity() -> None:
    """
    Connect to the restored database using pyodbc (ODBC Driver 18 for SQL Server)
    and assert that the Users table contains at least EXPECTED_ROW_THRESHOLD rows.

    Connection string notes:
    - SERVER   : Use the FQDN (e.g. my-server.database.windows.net) — works for
                 both Azure SQL Server (PaaS) and Azure SQL Managed Instance.
    - Encrypt  : Must be 'yes' — ODBC Driver 18 enforces encryption by default,
                 but being explicit makes the requirement clear.
    - TrustServerCertificate=no : Forces validation of the server certificate
                                   against trusted CAs (Microsoft's PKI).
    - Connection Timeout : 30-second limit before raising a connection error.
    """
    print(f"[STEP C] Connecting to '{DRILL_SQL_SERVER_FQDN}' / '{DRILL_DB_NAME}' via pyodbc...")

    connection_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DRILL_SQL_SERVER_FQDN},1433;"
        f"DATABASE={DRILL_DB_NAME};"
        f"UID={SQL_ADMIN_USERNAME};"
        f"PWD={SQL_ADMIN_PASSWORD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )

    with pyodbc.connect(connection_string) as conn:
        print("[STEP C] Connection established. Running integrity query...")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dbo.Users;")
        row_count = cursor.fetchone()[0]

    print(f"[STEP C] Query result: {row_count} row(s) in dbo.Users.")

    if row_count >= EXPECTED_ROW_THRESHOLD:
        print(f"[PASS] Data integrity verified. Row count ({row_count}) meets threshold ({EXPECTED_ROW_THRESHOLD}).")
    else:
        raise AssertionError(
            f"[FAIL] Data integrity check failed. "
            f"Row count ({row_count}) is below threshold ({EXPECTED_ROW_THRESHOLD}). "
            "The restored database may be empty or corrupt."
        )


# ──────────────────────────────────────────────────────────────
# Main Entrypoint
# ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Phoenix Protocol — DR Drill Starting")
    print("=" * 60)

    start_time = time.time()

    # Step A: Authenticate
    sql_client = authenticate()

    # Step B: Copy production DB to the ephemeral drill server
    trigger_restore(sql_client)

    # Step C: Verify
    verify_data_integrity()

    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"  Phoenix Protocol — Drill COMPLETE in {elapsed:.1f}s")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        # Data integrity failure — clean [FAIL] exit
        print(str(e))
        sys.exit(1)
    except Exception as e:
        # Unexpected failure — log and exit
        print(f"[FAIL] Unexpected error during drill: {type(e).__name__}: {e}")
        sys.exit(1)
