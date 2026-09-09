import final_version
import sys

# Override config for a quick test run
final_version.CONFIG["roles"] = ["Data Engineer"]
final_version.CONFIG["max_jobs_per_portal_per_role"] = 1
final_version.CONFIG["enable_all_sites"] = False
final_version.CONFIG["csv_file"] = "jobs_test_output.csv"
final_version.CONFIG["headless"] = True

print("Running validation test...")
final_version.run_harvester_v10()
print("Validation test complete!")
