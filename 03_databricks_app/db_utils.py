"""
db_utils.py — Databricks REST API Helper
Works in Databricks Apps, local dev, anywhere.
No spark session needed — uses SQL Statement Execution API via HTTP.
"""

import os, json, time, requests
from datetime import datetime, date
from pathlib import Path


# ── .env Loading ──────────────────────────────────────────────
# In Databricks Apps the working dir is /app/python/source_code/
# Try __file__ dir first (where this file lives), then parent dirs.
def _load_env():
    try:
        from dotenv import load_dotenv
        candidates = [
            Path(__file__).parent / ".env",          # 03_databricks_app/.env  ← primary
            Path(__file__).parent.parent / "01_local_scraper" / ".env",
            Path(__file__).parent.parent / ".env",
            Path.cwd() / ".env",
        ]
        for p in candidates:
            if p.exists():
                load_dotenv(p, override=False)
                break
    except ImportError:
        pass  # dotenv not installed — env vars must be set in Databricks App config

_load_env()


# ── Config ────────────────────────────────────────────────────
DATABRICKS_HOST  = os.getenv("DATABRICKS_HOST", "").rstrip("/")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
SQL_WAREHOUSE_ID = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", "")
CATALOG          = "jobs_automation_db"


def _get_headers():
    """Always build headers fresh so token updates are picked up."""
    token = os.getenv("DATABRICKS_TOKEN", DATABRICKS_TOKEN)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


# ── Core SQL Execution ────────────────────────────────────────
def _execute_statement(sql: str, wait_timeout: int = 30) -> dict:
    """Execute SQL via Databricks Statement Execution API."""
    host  = os.getenv("DATABRICKS_HOST", DATABRICKS_HOST).rstrip("/")
    wh_id = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", SQL_WAREHOUSE_ID)

    if not host:
        return {"error": "DATABRICKS_HOST not set"}
    if not wh_id:
        return {"error": "DATABRICKS_SQL_WAREHOUSE_ID not set — see .env"}

    url     = f"{host}/api/2.0/sql/statements"
    payload = {
        "warehouse_id":    wh_id,
        "statement":       sql,
        "wait_timeout":    f"{wait_timeout}s",
        "on_wait_timeout": "CANCEL",
        "format":          "JSON_ARRAY",
    }

    try:
        resp = requests.post(url, headers=_get_headers(), json=payload, timeout=60)
        data = resp.json()

        # Poll if still running
        if data.get("status", {}).get("state") == "RUNNING":
            stmt_id = data.get("statement_id")
            for _ in range(15):
                time.sleep(2)
                poll = requests.get(
                    f"{url}/{stmt_id}", headers=_get_headers(), timeout=30
                )
                data  = poll.json()
                state = data.get("status", {}).get("state", "")
                if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
                    break

        return data
    except Exception as e:
        return {"error": str(e)}


def execute_sql(sql: str) -> tuple:
    """
    Run any SQL. Returns (success: bool, rows: list[dict], error: str).
    """
    result = _execute_statement(sql)

    if "error" in result:
        return False, [], result["error"]

    state = result.get("status", {}).get("state", "")
    if state == "FAILED":
        err_obj = result.get("status", {}).get("error", {})
        err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
        return False, [], err_msg

    # Parse result rows
    rows     = []
    manifest = result.get("manifest", {})
    data_res = result.get("result", {})
    chunks   = data_res.get("data_array", []) or []
    cols     = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]

    for row in chunks:
        rows.append(dict(zip(cols, row)))

    return True, rows, ""


def query_df(sql: str):
    """Run SQL and return as pandas DataFrame. Returns empty DataFrame on error."""
    import pandas as pd
    ok, rows, err = execute_sql(sql)
    if not ok:
        # Don't crash the page — return empty df and let the page handle it
        return pd.DataFrame()
    return pd.DataFrame(rows)


# ── SQL Escaping ──────────────────────────────────────────────
def _escape(val) -> str:
    """
    Escape a Python value for use inside a SQL string literal.
    Uses SQL-standard double-single-quote '' instead of backslash \'.
    This avoids the Python 3.11 f-string backslash restriction.
    """
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return f"'{val.isoformat()}'"
    # Strings: escape ' → '' (SQL standard), strip newlines
    s = str(val).replace("'", "''").replace("\n", " ").replace("\r", " ")
    return f"'{s}'"


def esc(val) -> str:
    """
    Quick helper: returns val escaped for inline SQL without outer quotes.
    Use like: f"SET name = '{esc(some_var)}'"
    """
    if val is None:
        return ""
    return str(val).replace("'", "''").replace("\n", " ").replace("\r", " ")


def insert_row(table: str, row: dict) -> tuple:
    """
    Insert a single dict as a row. Returns (success: bool, error: str).
    """
    cols = ", ".join(row.keys())
    vals = ", ".join(_escape(v) for v in row.values())
    sql  = f"INSERT INTO {table} ({cols}) VALUES ({vals})"
    ok, _, err = execute_sql(sql)
    return ok, err


def update_row(table: str, set_dict: dict, where: str) -> tuple:
    """Update rows matching WHERE clause. Returns (success: bool, error: str)."""
    sets = ", ".join(f"{k} = {_escape(v)}" for k, v in set_dict.items())
    sql  = f"UPDATE {table} SET {sets} WHERE {where}"
    ok, _, err = execute_sql(sql)
    return ok, err


def get_env_status() -> dict:
    """Check which env vars are configured — safe to display."""
    host  = os.getenv("DATABRICKS_HOST", DATABRICKS_HOST)
    token = os.getenv("DATABRICKS_TOKEN", DATABRICKS_TOKEN)
    wh    = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", SQL_WAREHOUSE_ID)
    nvidia= os.getenv("NVIDIA_NIM_API_KEY", "")
    return {
        "host_set":       bool(host),
        "token_set":      bool(token),
        "warehouse_set":  bool(wh),
        "nvidia_set":     bool(nvidia),
        "host":           (host[:40] + "...") if len(host) > 40 else host,
    }
