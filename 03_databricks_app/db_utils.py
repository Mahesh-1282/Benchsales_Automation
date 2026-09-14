"""
db_utils.py — Local SQLite Database Helper
Replaces Databricks API with local SQLite.
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime, date
from pathlib import Path

# DB Path is one level up from 03_databricks_app, in the project root
DB_PATH = Path(__file__).parent.parent / "local_db.sqlite"

def _load_env():
    try:
        from dotenv import load_dotenv
        candidates = [
            Path(__file__).parent / ".env",          
            Path(__file__).parent.parent / "01_local_scraper" / ".env",
            Path(__file__).parent.parent / ".env",
            Path.cwd() / ".env",
        ]
        for p in candidates:
            if p.exists():
                load_dotenv(p, override=False)
                break
    except ImportError:
        pass

_load_env()

def get_connection():
    """Returns a new SQLite connection with dictionary row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_sql(sql: str) -> tuple:
    """
    Run any SQL. Returns (success: bool, rows: list[dict], error: str).
    """
    try:
        # SQLite doesn't natively support full Databricks syntax, but we try to support the basics.
        # Remove collate if present in queries
        sql = sql.replace("COLLATE UTF8_BINARY", "")
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            
            # If it's a SELECT, fetch rows
            if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("PRAGMA"):
                rows = [dict(row) for row in cursor.fetchall()]
            else:
                conn.commit()
                rows = []
                
        return True, rows, ""
    except Exception as e:
        return False, [], str(e)

def query_df(sql: str):
    """Run SQL and return as pandas DataFrame. Returns empty DataFrame on error."""
    ok, rows, err = execute_sql(sql)
    if not ok:
        print(f"SQL Error: {err}")
        return pd.DataFrame()
    return pd.DataFrame(rows)

def _escape(val) -> str:
    """
    Escape a Python value for use inside a SQL string literal.
    """
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "1" if val else "0" # SQLite boolean
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return f"'{val.isoformat()}'"
    # Strings: escape ' → '' 
    s = str(val).replace("'", "''").replace("\n", " ").replace("\r", " ")
    return f"'{s}'"

def esc(val) -> str:
    """
    Quick helper: returns val escaped for inline SQL without outer quotes.
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
    """Check which env vars are configured."""
    nvidia = os.getenv("NVIDIA_NIM_API_KEY", "")
    return {
        "host_set": True,      # Stubbed as True since we are local
        "token_set": True,     # Stubbed
        "warehouse_set": True, # Stubbed
        "nvidia_set": bool(nvidia),
        "host": f"Local SQLite: {DB_PATH.name}",
    }
