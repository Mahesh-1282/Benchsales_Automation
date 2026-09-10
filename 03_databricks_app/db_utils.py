"""
db_utils.py — Databricks REST API Helper
Works in Databricks Apps, local dev, anywhere.
No spark session needed — uses SQL Statement Execution API via HTTP.
"""

import os, json, time, uuid, requests
from datetime import datetime, date
from pathlib import Path

# Auto-load .env from multiple locations
def _load_env():
    try:
        from dotenv import load_dotenv
        base = Path(__file__).parent.parent
        for p in [base / "01_local_scraper" / ".env", base / ".env", Path.cwd() / ".env"]:
            if p.exists():
                load_dotenv(p, override=False)
                break
    except ImportError:
        pass

_load_env()

# ── Config ────────────────────────────────────────────────────
DATABRICKS_HOST  = os.getenv("DATABRICKS_HOST", "").rstrip("/")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
# SQL Warehouse ID — create a Serverless SQL Warehouse in Databricks
# Compute → SQL Warehouses → Create → Serverless → copy ID
SQL_WAREHOUSE_ID = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", "")

CATALOG = "jobs_automation_db"

HEADERS = {
    "Authorization": f"Bearer {DATABRICKS_TOKEN}",
    "Content-Type": "application/json",
}


def _execute_statement(sql: str, wait_timeout: int = 30) -> dict:
    """
    Execute SQL via Databricks Statement Execution API.
    Returns full response dict.
    """
    if not DATABRICKS_HOST or not DATABRICKS_TOKEN:
        return {"error": "DATABRICKS_HOST or DATABRICKS_TOKEN not set"}
    if not SQL_WAREHOUSE_ID:
        return {"error": "DATABRICKS_SQL_WAREHOUSE_ID not set"}

    url = f"{DATABRICKS_HOST}/api/2.0/sql/statements"
    payload = {
        "warehouse_id":  SQL_WAREHOUSE_ID,
        "statement":     sql,
        "wait_timeout":  f"{wait_timeout}s",
        "on_wait_timeout": "CANCEL",
        "format":        "JSON_ARRAY",
    }

    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=60)
        data = resp.json()

        # If still running, poll
        if data.get("status", {}).get("state") == "RUNNING":
            stmt_id = data.get("statement_id")
            for _ in range(10):
                time.sleep(3)
                poll = requests.get(f"{url}/{stmt_id}", headers=HEADERS, timeout=30)
                data = poll.json()
                state = data.get("status", {}).get("state", "")
                if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
                    break

        return data
    except Exception as e:
        return {"error": str(e)}


def execute_sql(sql: str) -> tuple[bool, list, str]:
    """
    Run any SQL. Returns (success, rows, error_message).
    rows = list of dicts
    """
    result = _execute_statement(sql)

    if "error" in result:
        return False, [], result["error"]

    state = result.get("status", {}).get("state", "")
    if state == "FAILED":
        err = result.get("status", {}).get("error", {}).get("message", "Unknown SQL error")
        return False, [], err

    # Parse rows
    rows = []
    manifest = result.get("manifest", {})
    data_res  = result.get("result", {})
    chunks    = data_res.get("data_array", []) or []
    cols      = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]

    for row in chunks:
        rows.append(dict(zip(cols, row)))

    return True, rows, ""


def query_df(sql: str):
    """Run SQL and return as pandas DataFrame."""
    import pandas as pd
    ok, rows, err = execute_sql(sql)
    if not ok:
        print(f"SQL Error: {err}")
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _escape(val) -> str:
    """Escape a value for SQL INSERT."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return f"'{val.isoformat()}'"
    # String — escape single quotes
    s = str(val).replace("'", "\\'").replace("\\n", " ").replace("\n", " ")
    return f"'{s}'"


def insert_row(table: str, row: dict) -> tuple[bool, str]:
    """
    Insert a single dict as a row into a Delta table via SQL INSERT.
    Returns (success, error_message).
    """
    cols = ", ".join(row.keys())
    vals = ", ".join(_escape(v) for v in row.values())
    sql = f"INSERT INTO {table} ({cols}) VALUES ({vals})"
    ok, _, err = execute_sql(sql)
    return ok, err


def update_row(table: str, set_dict: dict, where: str) -> tuple[bool, str]:
    """Update rows matching WHERE clause."""
    sets = ", ".join(f"{k} = {_escape(v)}" for k, v in set_dict.items())
    sql = f"UPDATE {table} SET {sets} WHERE {where}"
    ok, _, err = execute_sql(sql)
    return ok, err


def get_env_status() -> dict:
    """Check which env vars are configured."""
    return {
        "host_set":       bool(DATABRICKS_HOST),
        "token_set":      bool(DATABRICKS_TOKEN),
        "warehouse_set":  bool(SQL_WAREHOUSE_ID),
        "nvidia_set":     bool(os.getenv("NVIDIA_NIM_API_KEY")),
        "host":           DATABRICKS_HOST[:40] + "..." if len(DATABRICKS_HOST) > 40 else DATABRICKS_HOST,
    }
