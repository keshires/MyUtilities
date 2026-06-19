"""
EDFX Process Status Checker (Optimized Version v2)
This script:
1. Authenticates with Moody's SSO to get an access token
2. Loads distinct process IDs from Postgres (entity_custom_data)
3. Calls the EDFX status API for each process ID (with parallel processing)
4. Saves the results to a new Excel file in a configured output folder

Optimizations v2:
- Parallel API calls using ThreadPoolExecutor
- Connection pooling with requests.Session
- True batch DataFrame updates using .loc[]
- Single-pass entity error processing
- Configurable concurrency and sheet limits
- Memory-efficient data collection
- Option to limit error type sheets
"""

import asyncio
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import asyncpg
import pandas as pd
import requests
import urllib3
from dotenv import load_dotenv

from project_paths import output_dir, resolve_project_relative

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Suppress SSL warnings (use with caution in production)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== CONFIGURATION (see .env / .env.example) ====================

SSO_URL = os.getenv(
    "MOODYS_SSO_URL", "https://sso.moodysanalytics.com/sso-api/v1/token"
).strip()
SSO_USERNAME = (os.getenv("MOODYS_SSO_USERNAME") or "").strip()
SSO_PASSWORD = (os.getenv("MOODYS_SSO_PASSWORD") or "").strip()

EDFX_BASE_URL = os.getenv(
    "EDFX_BASE_URL",
    "https://api.edfx.moodysanalytics.com/edfx/v1/processes",
).strip()

_edfx_out = (os.getenv("EDFX_OUTPUT_FOLDER") or "").strip()
OUTPUT_FOLDER = (
    resolve_project_relative(_edfx_out)
    if _edfx_out
    else str(output_dir("edfx_process_status"))
)

DEFAULT_PROCESS_QUERY = """
SELECT DISTINCT financials_process_id, financials_process_status
FROM entity_custom_data
WHERE financials_process_status <> 'Completed'
""".strip()
EDFX_PROCESS_QUERY = (os.getenv("EDFX_PROCESS_QUERY") or DEFAULT_PROCESS_QUERY).strip()

POSTGRES_ENV_KEYS = (
    "TESSERA_POSTGRES_HOST",
    "TESSERA_POSTGRES_DB",
    "TESSERA_POSTGRES_USER",
    "TESSERA_POSTGRES_PASSWORD",
)

# Column names
PROCESS_ID_COLUMN = "financials_process_id"
PROCESS_STATUS_COLUMN = "financials_process_status"
RESULT_COLUMNS = {
    "status_message": "Status Endpoint Error Message",
    "status_value": "API_Status",
    "error_name": "API_Error_Name",
    "entity_error_count": "API_Entity_Error_Count",
    "affected_entities": "API_Affected_Entities",
    "error_file_url": "API_Error_File_URL",
    "entity_errors_detail": "API_Entity_Errors_Detail",
    "unique_error_types": "API_Unique_Error_Types",
}

# Row limit for testing (set to None to process all rows)
ROW_LIMIT = None  # Processing all rows

# Performance Configuration
MAX_WORKERS = 10  # Number of parallel API calls (adjust based on API rate limits)
REQUEST_TIMEOUT = 30  # Timeout for each API request in seconds
MAX_ERROR_TYPE_SHEETS = (
    50  # Limit separate sheets to top N error types (set to None for all)
)
SHOW_PROGRESS_EVERY = (
    10  # Show progress every N completed requests (reduces console I/O)
)

# Priority Error Types - These will appear as the first sheets (in order)
PRIORITY_ERRORS = [
    "Invalid value for currency. Valid values are ISO 4217 currency codes.",
    # Add more priority errors here if needed
]

# Manual token override (optional env EDFX_MANUAL_TOKEN)
MANUAL_TOKEN = (os.getenv("EDFX_MANUAL_TOKEN") or "").strip() or None

# ==================== OPTIMIZED FUNCTIONS ====================


def get_sso_token():
    """Authenticate with Moody's SSO and retrieve an access token."""
    print(f"\n{'='*60}")
    print("Authenticating with SSO...")
    print(f"{'='*60}")

    if not SSO_USERNAME or not SSO_PASSWORD:
        print(
            "✗ Set MOODYS_SSO_USERNAME and MOODYS_SSO_PASSWORD in .env (or use EDFX_MANUAL_TOKEN)."
        )
        return None

    payload = {
        "username": SSO_USERNAME,
        "password": SSO_PASSWORD,
        "grant_type": "password",
        "scope": "openid",
    }

    print(f"  URL: {SSO_URL}")
    if SSO_USERNAME:
        print(f"  Username: {SSO_USERNAME}")

    try:
        response = requests.post(
            SSO_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            verify=False,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:
            token_data = response.json()
            print(f"✓ Authentication successful!")

            id_token = token_data.get("id_token")
            access_token = token_data.get("access_token")

            if id_token:
                print(f"  → Using id_token for EDFX API")
                return id_token
            print(f"  → Using access_token for EDFX API")
            return access_token

        print(f"✗ Authentication failed! Status: {response.status_code}")
        return None

    except requests.exceptions.RequestException as e:
        print(f"✗ Authentication request failed: {e}")
        return None


def create_session():
    """Create a requests session with connection pooling."""
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS * 2, max_retries=3
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_status(session, access_token, task_data):
    """
    Fetch status for a single process. Optimized for parallel execution.
    task_data: (index, process_id, tenant_id)
    Returns: (index, process_id, tenant_id, parsed_result, entity_errors_list)
    """
    idx, process_id, tenant_id = task_data
    url = f"{EDFX_BASE_URL}/{process_id}/status"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = session.get(
            url, headers=headers, verify=False, timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            result = {"success": True, "status_code": 200, "response": response.json()}
        else:
            try:
                error_detail = response.json()
            except:
                error_detail = response.text
            result = {
                "success": False,
                "status_code": response.status_code,
                "response": error_detail,
            }

    except requests.exceptions.RequestException as e:
        result = {"success": False, "status_code": "Error", "response": str(e)}

    # Parse inline to avoid extra function call overhead
    parsed, entity_errors = parse_result_inline(result, process_id, tenant_id)
    return (idx, process_id, tenant_id, result["success"], parsed, entity_errors)


def parse_result_inline(result, process_id, tenant_id):
    """
    Inline optimized parsing. Returns (parsed_dict, entity_errors_list).
    Combined parsing and entity error collection in single pass.
    """
    parsed = {
        "status_message": "",
        "status_value": "",
        "error_name": "",
        "entity_error_count": 0,
        "affected_entities": "",
        "error_file_url": "",
        "entity_errors_detail": "",
        "unique_error_types": "",
    }
    entity_errors = []

    if not result["success"]:
        parsed["status_message"] = f"HTTP {result['status_code']}: {result['response']}"
        parsed["status_value"] = f"HTTP Error {result['status_code']}"
        return parsed, entity_errors

    response_data = result["response"]
    if not isinstance(response_data, dict):
        parsed["status_message"] = str(response_data)
        parsed["status_value"] = str(response_data)
        return parsed, entity_errors

    status = response_data.get("status", "Unknown")
    parsed["status_value"] = status
    parts = [f"Status: {status}"]

    errors = response_data.get("errors", [])
    if errors:
        error_obj = errors[0]  # Process first error object
        error_name = error_obj.get("error_name", "")
        error_message = error_obj.get("error_message", "")

        if error_name:
            parsed["error_name"] = error_name
            parts.append(f"Error Name: {error_name}")
        if error_message:
            parts.append(f"Error Message: {error_message}")

        entity_errors_raw = error_obj.get("entityErrors", [])
        if entity_errors_raw:
            count = len(entity_errors_raw)
            parsed["entity_error_count"] = count
            parts.append(f"Entity Errors Count: {count}")

            # Single pass collection
            unique_msgs = set()
            entity_ids = []
            details = []

            for e in entity_errors_raw:
                eid = e.get("entityIdentifier", "")
                msg = e.get("errorMessage", "")
                date = e.get("financialStatementDate", "")

                if msg:
                    unique_msgs.add(msg)
                if eid:
                    entity_ids.append(eid)

                details.append(f"Entity: {eid} | Error: {msg} | Date: {date}")

                # Collect for separate sheets
                entity_errors.append(
                    {
                        "process_id": process_id,
                        "tenant_id": tenant_id,
                        "entityIdentifier": eid,
                        "errorMessage": msg,
                        "financialStatementDate": date,
                    }
                )

            if unique_msgs:
                parsed["unique_error_types"] = " | ".join(sorted(unique_msgs))
            if entity_ids:
                parsed["affected_entities"] = ", ".join(entity_ids)
            parsed["entity_errors_detail"] = "\n".join(details)

    error_file = response_data.get("errorFile", "")
    if error_file:
        parsed["error_file_url"] = error_file
        parts.append("Error File: Available")

    parsed["status_message"] = " | ".join(parts)
    return parsed, entity_errors


def missing_postgres_env() -> list[str]:
    return [key for key in POSTGRES_ENV_KEYS if not (os.getenv(key) or "").strip()]


async def _fetch_process_rows() -> list[asyncpg.Record]:
    conn = await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"],
        port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"],
        user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"],
        ssl="prefer",
    )
    try:
        return await conn.fetch(EDFX_PROCESS_QUERY)
    finally:
        await conn.close()


def load_process_dataframe() -> pd.DataFrame:
    """Load distinct process IDs and DB status from Postgres."""
    rows = asyncio.run(_fetch_process_rows())
    if not rows:
        return pd.DataFrame(columns=[PROCESS_ID_COLUMN, PROCESS_STATUS_COLUMN])

    df = pd.DataFrame([dict(row) for row in rows])
    if PROCESS_ID_COLUMN not in df.columns:
        raise ValueError(
            f"Query must return '{PROCESS_ID_COLUMN}'. Got columns: {list(df.columns)}"
        )
    return df


def setup_output_file(base_name="EDFX_ProcessStatus"):
    """Create output folder and return output Excel path."""
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    print(f"✓ Output folder ready: {OUTPUT_FOLDER}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{base_name}_StatusResults_{timestamp}.xlsx"
    return os.path.join(OUTPUT_FOLDER, filename)


def process_status_data(access_token, df):
    """Fetch EDFX status for each DB process ID and write one .xlsx result."""
    print(f"\n{'='*60}")
    print("STEP 2: Setting Up Output...")
    print(f"{'='*60}")

    output_file_path = setup_output_file()
    print(f"  Output file: {output_file_path}")

    print(f"\n{'='*60}")
    print("STEP 3: Loaded Process IDs from Database")
    print(f"{'='*60}")
    print(f"  Rows: {len(df)}")

    if PROCESS_ID_COLUMN not in df.columns:
        print(f"✗ Column '{PROCESS_ID_COLUMN}' not found!")
        return False

    # Add all result columns at once (entity_error_count is numeric)
    for key, col in RESULT_COLUMNS.items():
        if col not in df.columns:
            df[col] = 0 if key == "entity_error_count" else ""

    print(f"\n{'='*60}")
    print("STEP 4: Processing Process IDs (Parallel)...")
    print(f"{'='*60}")
    print(f"  Workers: {MAX_WORKERS} | Timeout: {REQUEST_TIMEOUT}s")

    total_rows = len(df)
    rows_to_process = min(ROW_LIMIT or total_rows, total_rows)

    if ROW_LIMIT:
        print(f"  ⚠ ROW LIMIT: {rows_to_process} of {total_rows}")

    # Prepare tasks using list comprehension (faster than loop)
    tasks = [
        (
            idx,
            str(df.iloc[idx][PROCESS_ID_COLUMN]).strip(),
            df.iloc[idx].get("tenant_id", ""),
        )
        for idx in range(rows_to_process)
        if pd.notna(df.iloc[idx][PROCESS_ID_COLUMN])
        and str(df.iloc[idx][PROCESS_ID_COLUMN]).strip()
    ]

    print(f"  Valid tasks: {len(tasks)}")

    # Pre-allocate result storage
    results_data = {}  # idx -> parsed dict
    all_entity_errors = []
    error_counts = defaultdict(int)
    success_count = 0
    error_count = 0

    session = create_session()
    start_time = time.time()

    # Parallel processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_status, session, access_token, task): task
            for task in tasks
        }

        completed = 0
        for future in as_completed(futures):
            idx, process_id, tenant_id, success, parsed, entity_errors = future.result()
            completed += 1

            results_data[idx] = parsed
            all_entity_errors.extend(entity_errors)

            # Count errors
            for e in entity_errors:
                if e["errorMessage"]:
                    error_counts[e["errorMessage"]] += 1

            if success:
                success_count += 1
            else:
                error_count += 1

            # Progress every N items (reduces I/O overhead)
            if completed % SHOW_PROGRESS_EVERY == 0 or completed == len(tasks):
                pct = completed * 100 // len(tasks)
                print(
                    f"  Progress: {completed}/{len(tasks)} ({pct}%) - Success: {success_count}, Failed: {error_count}"
                )

    session.close()
    elapsed = time.time() - start_time

    print(
        f"\n  ✓ API calls completed in {elapsed:.2f}s ({elapsed/len(tasks)*1000:.0f}ms avg)"
    )

    # BATCH UPDATE DataFrame using .loc[] (much faster than multiple .at[] calls)
    print(f"  Updating DataFrame (batch mode)...")

    for key, col_name in RESULT_COLUMNS.items():
        default = 0 if key == "entity_error_count" else ""
        values = {idx: parsed.get(key, default) for idx, parsed in results_data.items()}
        if values:
            assign_values = list(values.values())
            if key != "entity_error_count":
                assign_values = [
                    "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
                    for v in assign_values
                ]
            df.loc[list(values.keys()), col_name] = assign_values

    # Mark skipped rows
    skipped_indices = [idx for idx in range(rows_to_process) if idx not in results_data]
    if skipped_indices:
        df.loc[skipped_indices, RESULT_COLUMNS["status_message"]] = (
            "Skipped - Empty process ID"
        )
        df.loc[skipped_indices, RESULT_COLUMNS["status_value"]] = "Skipped"

    print(f"\n{'='*60}")
    print("STEP 5: Saving Results (Multiple Sheets)...")
    print(f"{'='*60}")

    try:
        with pd.ExcelWriter(output_file_path, engine="openpyxl") as writer:
            # Sheet 1: Main Results
            df.to_excel(writer, sheet_name="All_Results", index=False)
            print(f"  ✓ 'All_Results': {len(df)} rows")

            # Sheet 2: Error Summary
            if error_counts:
                sorted_errors = sorted(error_counts.items(), key=lambda x: -x[1])
                summary_df = pd.DataFrame(
                    [
                        {"Error_Message": msg, "Total_Count": cnt}
                        for msg, cnt in sorted_errors
                    ]
                )
                summary_df.to_excel(writer, sheet_name="Error_Summary", index=False)
                print(f"  ✓ 'Error_Summary': {len(summary_df)} error types")

            # Sheet 3: All Entity Errors
            if all_entity_errors:
                entity_df = pd.DataFrame(all_entity_errors)
                entity_df.to_excel(writer, sheet_name="All_Entity_Errors", index=False)
                print(f"  ✓ 'All_Entity_Errors': {len(entity_df)} errors")

                # Create sheets for error types with PRIORITY ERRORS FIRST
                unique_errors = set(entity_df["errorMessage"].dropna().unique())

                # Build ordered list: Priority errors first, then top errors by count
                ordered_errors = []

                # 1. Add priority errors first (if they exist in data)
                for priority_err in PRIORITY_ERRORS:
                    if priority_err in unique_errors:
                        ordered_errors.append(priority_err)
                        unique_errors.discard(priority_err)
                        print(f"  ★ Priority error found: '{priority_err[:50]}...'")

                # 2. Add remaining top errors by count
                remaining_sorted = [
                    (msg, cnt) for msg, cnt in sorted_errors if msg in unique_errors
                ]

                # Limit total sheets
                remaining_slots = (
                    MAX_ERROR_TYPE_SHEETS or len(remaining_sorted)
                ) - len(ordered_errors)
                if remaining_slots > 0:
                    ordered_errors.extend(
                        [msg for msg, _ in remaining_sorted[:remaining_slots]]
                    )

                # Create sheets in order
                for i, error_msg in enumerate(ordered_errors):
                    if not error_msg:
                        continue

                    subset = entity_df[entity_df["errorMessage"] == error_msg]

                    # Mark priority errors with special prefix
                    is_priority = error_msg in PRIORITY_ERRORS
                    prefix = "★" if is_priority else "Err"
                    safe_name = "".join(
                        c if c.isalnum() or c in " _-" else "_"
                        for c in str(error_msg)[:18]
                    )
                    sheet_name = f"{prefix}{i+1}_{safe_name}"[:31]

                    subset.to_excel(writer, sheet_name=sheet_name, index=False)

                priority_count = sum(1 for e in ordered_errors if e in PRIORITY_ERRORS)
                print(
                    f"  ✓ Created {len(ordered_errors)} error sheets ({priority_count} priority, {len(ordered_errors)-priority_count} others)"
                )

        print(f"\n✓ Saved to: {output_file_path}")

    except Exception as e:
        print(f"✗ Error saving: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Rows Processed: {rows_to_process}")
    print(
        f"  API Success: {success_count} | Failed: {error_count} | Skipped: {len(skipped_indices)}"
    )
    print(
        f"  Entity Errors: {len(all_entity_errors)} | Unique Types: {len(error_counts)}"
    )
    print(f"  Processing Time: {elapsed:.2f}s")

    if error_counts:
        print(f"\n{'='*60}")
        print("TOP ERROR TYPES")
        print(f"{'='*60}")
        for msg, cnt in sorted(error_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  [{cnt:4d}] {msg[:75]}{'...' if len(msg) > 75 else ''}")

    return True


def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    print("EDFX PROCESS STATUS CHECKER (Optimized v2)")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    missing = missing_postgres_env()
    if missing:
        print(
            "\n✗ Set Postgres settings in .env: "
            + ", ".join(missing)
            + " (see .env.example)."
        )
        return

    print(f"\n{'='*60}")
    print("STEP 1: Loading Process IDs from Database...")
    print(f"{'='*60}")
    print(f"  Query:\n  {EDFX_PROCESS_QUERY}")

    try:
        df = load_process_dataframe()
    except Exception as e:
        print(f"\n✗ Database query failed: {e}")
        return

    if df.empty:
        print("\n✗ No process IDs returned from database.")
        return

    print(f"✓ Loaded {len(df)} distinct process ID(s)")

    access_token = MANUAL_TOKEN or get_sso_token()

    if not access_token:
        print("\n✗ No access token. Exiting.")
        return

    all_ok = process_status_data(access_token, df)

    print("\n" + "=" * 60)
    print("✓ COMPLETED!" if all_ok else "✗ COMPLETED WITH ERRORS")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
