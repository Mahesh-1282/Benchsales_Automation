# Databricks Notebook — Daily Job Harvester
# ==========================================
# Schedule this as a Databricks Job:
#   Cluster: Standard_DS3_v2 or similar
#   Schedule: Daily at 9:00 AM (cron: 0 9 * * *)
#   This notebook: /Shared/JobHarvester/daily_job

# ============================================================
# CELL 1 — Install dependencies
# ============================================================
# %pip install playwright requests tabulate duckduckgo-search
# dbutils.library.restartPython()

# ============================================================
# CELL 2 — Install Playwright browser
# ============================================================
# import subprocess
# result = subprocess.run(
#     ["playwright", "install", "chromium", "--with-deps"],
#     capture_output=True, text=True, timeout=300
# )
# print(result.stdout[-2000:] if result.stdout else "")
# print(result.stderr[-1000:] if result.stderr else "")

# ============================================================
# CELL 3 — Load and run the agent
# ============================================================
"""
HOW TO USE IN DATABRICKS:
==========================

Option A: Upload script to DBFS and run
  1. Upload job_ai_agent.py to DBFS:
     dbutils.fs.cp("file:/path/to/job_ai_agent.py", "dbfs:/FileStore/job_ai_agent.py")
  
  2. In notebook cell:
     with open('/dbfs/FileStore/job_ai_agent.py') as f:
         exec(f.read())
     
     # Override output path for DBFS
     CONFIG["output_csv"] = "/dbfs/FileStore/jobs/jobs_ai_agent_output.csv"
     CONFIG["nvidia_api_key"] = dbutils.secrets.get("nvidia", "api_key")
     
     # Run
     jobs = run_ai_agent()

Option B: Use as Databricks Workflow Task
  - Task type: Python script
  - Script path: /dbfs/FileStore/job_ai_agent.py
  - Parameters: []
  - Environment: NVIDIA_NIM_API_KEY = {{secrets/nvidia/api_key}}

Option C: Delta Lake output (Databricks native)
  - Use the run_databricks_with_delta() function below
"""

import os

def run_databricks_with_delta():
    """
    Full Databricks pipeline with Delta Lake output.
    Saves to Delta table for easy SQL querying.
    """
    # Load and execute the agent script
    with open('/dbfs/FileStore/job_ai_agent.py') as f:
        exec(f.read(), globals())

    # Override config for Databricks
    CONFIG["output_csv"] = "/dbfs/tmp/jobs_ai_agent_output.csv"
    CONFIG["nvidia_api_key"] = os.getenv(
        "NVIDIA_NIM_API_KEY",
        dbutils.secrets.get(scope="nvidia", key="api_key")
    )

    # Run the agent
    jobs = run_ai_agent()

    # Convert to Spark DataFrame and save as Delta table
    from pyspark.sql import SparkSession
    from pyspark.sql.types import *

    spark = SparkSession.builder.getOrCreate()

    # Read the CSV output
    df = spark.read.option("header", "true") \
                   .option("escape", '"') \
                   .csv("/dbfs/tmp/jobs_ai_agent_output.csv")

    # Save to Delta Lake table (auto-merges new records)
    df.write \
      .format("delta") \
      .mode("overwrite") \
      .option("mergeSchema", "true") \
      .saveAsTable("jobs_harvester.daily_jobs")

    print(f"✅ Saved {df.count()} jobs to Delta table: jobs_harvester.daily_jobs")

    # Print sample
    spark.sql("""
        SELECT job_title, company_name, location, salary_range, 
               validation_score, validation_status, tech_stack
        FROM jobs_harvester.daily_jobs
        WHERE validation_status = 'Valid'
        ORDER BY CAST(validation_score AS INT) DESC
        LIMIT 10
    """).show(truncate=50)

    return df


# ============================================================
# DATABRICKS JOB CONFIG (for job_settings.json)
# ============================================================
DATABRICKS_JOB_CONFIG = {
    "name": "US IT Job Harvester - Daily",
    "schedule": {
        "quartz_cron_expression": "0 0 9 * * ?",  # 9 AM daily
        "timezone_id": "America/New_York",
        "pause_status": "UNPAUSED"
    },
    "tasks": [
        {
            "task_key": "job_harvester",
            "description": "Harvest US IT jobs using AI agent",
            "existing_cluster_id": "<YOUR_CLUSTER_ID>",  # Fill this in
            "notebook_task": {
                "notebook_path": "/Shared/JobHarvester/daily_job",
                "source": "WORKSPACE"
            },
            "libraries": [
                {"pypi": {"package": "playwright"}},
                {"pypi": {"package": "requests"}},
                {"pypi": {"package": "tabulate"}},
                {"pypi": {"package": "duckduckgo-search"}},
            ],
            "email_notifications": {
                "on_failure": ["your-email@example.com"],
                "no_alert_for_skipped_runs": True
            },
            "timeout_seconds": 7200,  # 2 hours max
            "max_retries": 2,
            "retry_on_timeout": True
        }
    ],
    "email_notifications": {
        "on_success": ["your-email@example.com"]
    },
    "max_concurrent_runs": 1,
    "tags": {
        "project": "benchsales-automation",
        "env": "production"
    }
}

# ============================================================
# HOW TO SCHEDULE IN DATABRICKS
# ============================================================
print("""
╔══════════════════════════════════════════════════════════════╗
║  DATABRICKS SETUP GUIDE                                     ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  1. Upload job_ai_agent.py to DBFS:                        ║
║     Databricks → Data → DBFS → Upload                      ║
║     Path: /FileStore/job_ai_agent.py                        ║
║                                                             ║
║  2. Set NVIDIA API Key as Secret:                           ║
║     databricks secrets create-scope --scope nvidia          ║
║     databricks secrets put --scope nvidia --key api_key     ║
║                                                             ║
║  3. Create Notebook in /Shared/JobHarvester/daily_job:     ║
║     Cell 1: %pip install playwright requests tabulate       ║
║     Cell 2: exec(open('/dbfs/FileStore/job_ai_agent.py').read()) ║
║     Cell 3: CONFIG["nvidia_api_key"] = dbutils.secrets.get(...) ║
║     Cell 4: jobs = run_ai_agent()                          ║
║                                                             ║
║  4. Schedule the Job:                                       ║
║     Workflows → Create Job → Select Notebook               ║
║     Schedule: 0 9 * * * (9 AM daily)                       ║
║     Cluster: Standard_DS3_v2                                ║
║                                                             ║
║  5. Output:                                                  ║
║     CSV: /dbfs/FileStore/jobs_ai_agent_output.csv          ║
║     Delta: jobs_harvester.daily_jobs                        ║
║                                                             ║
╚══════════════════════════════════════════════════════════════╝
""")
