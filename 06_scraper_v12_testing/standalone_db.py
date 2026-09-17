"""
standalone_db.py — Standalone SQLite Database Helper
Zero Databricks dependencies. Pure SQLite for desktop app use.
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime, date
from pathlib import Path

# DB Path: one level up from this folder, in the project root
DB_PATH = Path(__file__).parent.parent / "local_db.sqlite"


def get_connection():
    """Returns a new SQLite connection with dictionary row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def execute_sql(sql: str) -> tuple:
    """Run any SQL. Returns (success: bool, rows: list[dict], error: str)."""
    try:
        sql = sql.replace("COLLATE UTF8_BINARY", "")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("PRAGMA"):
                rows = [dict(row) for row in cursor.fetchall()]
            else:
                conn.commit()
                rows = []
        return True, rows, ""
    except Exception as e:
        return False, [], str(e)


def query_df(sql: str):
    """Run SQL and return as pandas DataFrame."""
    ok, rows, err = execute_sql(sql)
    if not ok:
        print(f"SQL Error: {err}")
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _escape(val) -> str:
    """Escape a Python value for use inside a SQL string literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return f"'{val.isoformat()}'"
    s = str(val).replace("'", "''").replace("\n", " ").replace("\r", " ")
    return f"'{s}'"


def esc(val) -> str:
    """Quick helper: returns val escaped for inline SQL."""
    if val is None:
        return ""
    return str(val).replace("'", "''").replace("\n", " ").replace("\r", " ")


def insert_row(table: str, row: dict) -> tuple:
    """Insert a single dict as a row. Returns (success: bool, error: str)."""
    cols = ", ".join(row.keys())
    vals = ", ".join(_escape(v) for v in row.values())
    sql = f"INSERT INTO {table} ({cols}) VALUES ({vals})"
    ok, _, err = execute_sql(sql)
    return ok, err


def update_row(table: str, set_dict: dict, where: str) -> tuple:
    """Update rows matching WHERE clause. Returns (success: bool, error: str)."""
    sets = ", ".join(f"{k} = {_escape(v)}" for k, v in set_dict.items())
    sql = f"UPDATE {table} SET {sets} WHERE {where}"
    ok, _, err = execute_sql(sql)
    return ok, err


def init_bronze_table():
    """Create jobs_harvested_bronze table if not exists."""
    sql = """
    CREATE TABLE IF NOT EXISTS jobs_harvested_bronze (
      id TEXT,
      job_hash TEXT,
      fetch_date DATE,
      portal TEXT,
      search_keyword TEXT,
      job_title TEXT,
      company_name TEXT,
      location TEXT,
      remote_type TEXT,
      salary_range TEXT,
      experience_years TEXT,
      tech_stack TEXT,
      posted_date TEXT,
      job_description TEXT,
      description_length INTEGER,
      roles_responsibilities TEXT,
      requirements_section TEXT,
      roles_summary TEXT,
      apply_link TEXT,
      easy_apply_link TEXT,
      company_career_url TEXT,
      company_website TEXT,
      hr_email TEXT,
      job_id TEXT,
      visa_sponsorship BOOLEAN,
      validation_score INTEGER,
      validation_status TEXT,
      ai_summary TEXT,
      detail_fetched BOOLEAN
    )
    """
    ok, _, err = execute_sql(sql)
    if ok:
        print(f"✅ Bronze table ready at {DB_PATH}")
    else:
        print(f"❌ Bronze table error: {err}")
    return ok
