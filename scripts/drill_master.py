"""
drill_master.py — Phoenix Protocol Core Script
================================================
Performs the "Game Day" DR drill cycle:
  Step A: Read earliest_restore_date from the Production database object.
  Step B: Restore it to the ephemeral Drill SQL Server.
  Step C: Verify data integrity via a row-count query.

All configuration is read from environment variables — no hardcoded values.
Exit codes: 0 = PASS, 1 = FAIL
"""

import os
import sys
import time
from datetime import timezone

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
# Step A: Authenticate & Identify PITR Target Time
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


def get_latest_restore_point(client: SqlManagementClient) -> object:
    """
    Return the PITR target time for the production database.

    Reads `earliest_restore_date` directly from the Database object via
    `databases.get()`. This property is the canonical, authoritative timestamp
    that the Azure Portal also surfaces, and is always consistent with the
    service's internal PITR window — unlike `restore_points.list_by_database()`,
    which can return objects with a null `restore_point_creation_date` while the
    initial backup is still being written.

    Raises RuntimeError if `earliest_restore_date` is None, meaning the
    production database has not yet completed its first automated backup.
    """
    print(
        f"[STEP A] Fetching database object for '{PROD_DB_NAME}' "
        f"on '{PROD_SQL_SERVER_NAME}'..."
    )

    prod_db = client.databases.get(
        resource_group_name=PROD_RESOURCE_GROUP,
        server_name=PROD_SQL_SERVER_NAME,
        database_name=PROD_DB_NAME,
    )

    restore_time = prod_db.earliest_restore_date

    if restore_time is None:
        raise RuntimeError(
            f"'earliest_restore_date' is None for database '{PROD_DB_NAME}'. "
            "The initial Azure automated backup has not yet completed. "
            "Re-run the drill once the first backup finishes "
            "(typically within 60 minutes of database creation)."
        )

    # Ensure the datetime is timezone-aware (Azure SDK returns UTC-naive datetimes)
    if restore_time.tzinfo is None:
        restore_time = restore_time.replace(tzinfo=timezone.utc)

    print(f"[STEP A] PITR target time (earliest_restore_date): {restore_time.isoformat()}")
    return restore_time


# ──────────────────────────────────────────────────────────────
# Step B: Trigger Point-in-Time Restore
# ──────────────────────────────────────────────────────────────

def trigger_restore(client: SqlManagementClient, restore_time: object) -> None:
    """
    Restore the production database to the drill SQL Server using
    CreateMode=PointInTimeRestore. Blocks until the operation completes.

    Notes on Azure SDK parameter names (azure-mgmt-sql >= 3.x):
    - `create_mode`          : "PointInTimeRestore"
    - `source_database_id`   : full ARM resource ID of the source database
    - `restore_point_in_time`: timezone-aware datetime object
    - `sku`                  : intentionally omitted — the SDK rejects a Sku
                               override during a cross-server PointInTimeRestore.
                               The restored database inherits the source SKU and
                               can be scaled independently after the restore.
    """
    print(f"[STEP B] Triggering restore to '{DRILL_SQL_SERVER_NAME}' / '{DRILL_DB_NAME}'...")
    print(f"[STEP B] Source:        {PROD_SQL_SERVER_NAME}/{PROD_DB_NAME}")
    print(f"[STEP B] Restore point: {restore_time.isoformat()}")
    print(f"[STEP B] Target region: {DRILL_LOCATION}")
    print("[STEP B] This operation can take 5–15 minutes. Waiting...")

    # Build the ARM resource ID of the source (production) database
    source_db_id = (
        f"/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{PROD_RESOURCE_GROUP}"
        f"/providers/Microsoft.Sql/servers/{PROD_SQL_SERVER_NAME}"
        f"/databases/{PROD_DB_NAME}"
    )

    restore_params = Database(
        location=DRILL_LOCATION,
        create_mode="PointInTimeRestore",
        source_database_id=source_db_id,
        restore_point_in_time=restore_time,
        # SKU is deliberately omitted — see docstring above.
    )

    # begin_create_or_update returns a LROPoller; .result() blocks until done
    poller = client.databases.begin_create_or_update(
        resource_group_name=DRILL_RESOURCE_GROUP,
        server_name=DRILL_SQL_SERVER_NAME,
        database_name=DRILL_DB_NAME,
        parameters=restore_params,
    )
    poller.result()  # Blocks — raises CloudError / HttpResponseError if op fails

    print(f"[STEP B] Restore complete. Database '{DRILL_DB_NAME}' is ready.")


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

    # Step A: Auth + read earliest_restore_date from production DB object
    sql_client   = authenticate()
    restore_time = get_latest_restore_point(sql_client)

    # Step B: Restore
    trigger_restore(sql_client, restore_time)

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
