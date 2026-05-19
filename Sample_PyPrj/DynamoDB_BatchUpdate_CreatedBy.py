"""
DynamoDB Batch Update Script - Update CreatedBy Field
======================================================
This script updates the 'CreatedBy' field for records in DynamoDB tables
in batches of 240 records at a time.

PREREQUISITES:
--------------
1. Install required packages:
   pip install boto3

2. Configure AWS credentials (choose one method):

   Method A - AWS CLI (Recommended):
   - Install AWS CLI: https://aws.amazon.com/cli/
   - Run: aws configure
   - Enter your Access Key ID, Secret Access Key, and region

   Method B - Environment Variables:
   - Set these environment variables:
     SET AWS_ACCESS_KEY_ID=your_access_key
     SET AWS_SECRET_ACCESS_KEY=your_secret_key
     SET AWS_DEFAULT_REGION=us-east-1

   Method C - AWS Credentials File:
   - Create/edit file: C:\\Users\\<username>\\.aws\\credentials
   - Add profiles for each environment:
     [qa]
     aws_access_key_id = YOUR_QA_ACCESS_KEY
     aws_secret_access_key = YOUR_QA_SECRET_KEY

     [prod]
     aws_access_key_id = YOUR_PROD_ACCESS_KEY
     aws_secret_access_key = YOUR_PROD_SECRET_KEY

RUNNING THE SCRIPT:
-------------------
Step 1: Update QA Environment
   1. Set ENVIRONMENT = "QA" in the configuration below
   2. Verify QA_TABLE_NAME and other QA settings
   3. Run: python DynamoDB_BatchUpdate_CreatedBy.py
   4. Review the scan results and confirm when prompted
   5. Verify updates in AWS Console

Step 2: Update PROD Environment (after QA validation)
   1. Set ENVIRONMENT = "PROD" in the configuration below
   2. Verify PROD_TABLE_NAME and other PROD settings
   3. Run: python DynamoDB_BatchUpdate_CreatedBy.py
   4. Review the scan results and confirm when prompted
   5. Verify updates in AWS Console

SAFETY FEATURES:
----------------
- Dry run mode (DRY_RUN = True) to preview without making changes
- Confirmation prompt before updates
- Detailed logging of all operations
- Error tracking and reporting
"""

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import sys
from datetime import datetime

# ==================== ENVIRONMENT SELECTION ====================
# Change this to switch between QA and PROD
ENVIRONMENT = "QA"  # Options: "QA" or "PROD"

# ==================== SAFETY SETTINGS ====================
DRY_RUN = True  # Set to False to actually perform updates (START WITH TRUE!)

# ==================== QA ENVIRONMENT CONFIGURATION ====================
QA_CONFIG = {
    "AWS_REGION": "us-east-1",  # QA AWS region
    "AWS_PROFILE": "qa",  # AWS credentials profile name (or None for default)
    "TABLE_NAME": "YourTableName-QA",  # QA DynamoDB table name
    "DESCRIPTION": "QA Environment",
}

# ==================== PROD ENVIRONMENT CONFIGURATION ====================
PROD_CONFIG = {
    "AWS_REGION": "us-east-1",  # PROD AWS region
    "AWS_PROFILE": "prod",  # AWS credentials profile name (or None for default)
    "TABLE_NAME": "YourTableName-Prod",  # PROD DynamoDB table name
    "DESCRIPTION": "PRODUCTION Environment",
}

# ==================== UPDATE CONFIGURATION ====================
# These settings apply to both environments

# Primary key configuration - UPDATE THESE TO MATCH YOUR TABLE SCHEMA
PARTITION_KEY = "pk"  # Your partition key attribute name
SORT_KEY = "sk"  # Your sort key attribute name (set to None if table has no sort key)

# Field to update
FIELD_TO_UPDATE = "CreatedBy"

# Filter criteria - find records where CreatedBy equals this value
CURRENT_VALUE_TO_FIND = "old_user@example.com"  # The current value to search for

# New value to set
NEW_VALUE_TO_SET = "new_user@example.com"  # The new value to update to

# Batch processing settings
BATCH_SIZE = 240  # Number of records per batch
MAX_WORKERS = 25  # Parallel threads (DynamoDB recommended max is 25)
DELAY_BETWEEN_BATCHES = 0.5  # Seconds to wait between batches (helps avoid throttling)

# ==================== OPTIONAL: ADDITIONAL FILTER ====================
# Set to None to update ALL records matching CURRENT_VALUE_TO_FIND
# Or specify additional filter like: {"field_name": "field_value"}
ADDITIONAL_FILTER = None  # Example: {"tenant_id": "tenant123"}

# ==================== SCRIPT CODE (No changes needed below) ====================


def get_active_config():
    """Get configuration for the selected environment."""
    if ENVIRONMENT.upper() == "PROD":
        return PROD_CONFIG
    return QA_CONFIG


def get_dynamodb_resource(config):
    """Get DynamoDB resource with appropriate credentials."""
    boto_config = Config(retries={"max_attempts": 3, "mode": "adaptive"})

    if config.get("AWS_PROFILE"):
        session = boto3.Session(profile_name=config["AWS_PROFILE"])
        return session.resource(
            "dynamodb", region_name=config["AWS_REGION"], config=boto_config
        )
    else:
        return boto3.resource(
            "dynamodb", region_name=config["AWS_REGION"], config=boto_config
        )


def scan_records_to_update(table):
    """
    Scan table to find all records matching the filter criteria.
    Returns list of items with their primary keys.
    """
    print(
        f"\nScanning for records where {FIELD_TO_UPDATE} = '{CURRENT_VALUE_TO_FIND}'..."
    )
    if ADDITIONAL_FILTER:
        print(f"  Additional filter: {ADDITIONAL_FILTER}")

    records_to_update = []

    # Build filter expression
    filter_expr = Attr(FIELD_TO_UPDATE).eq(CURRENT_VALUE_TO_FIND)

    if ADDITIONAL_FILTER:
        for field, value in ADDITIONAL_FILTER.items():
            filter_expr = filter_expr & Attr(field).eq(value)

    # Build projection expression (only fetch keys)
    projection = PARTITION_KEY
    if SORT_KEY:
        projection += f", {SORT_KEY}"

    scan_kwargs = {"FilterExpression": filter_expr, "ProjectionExpression": projection}

    done = False
    start_key = None
    total_scanned = 0

    while not done:
        if start_key:
            scan_kwargs["ExclusiveStartKey"] = start_key

        response = table.scan(**scan_kwargs)
        records_to_update.extend(response.get("Items", []))
        total_scanned += response.get("ScannedCount", 0)

        start_key = response.get("LastEvaluatedKey")
        done = start_key is None

        print(
            f"  Scanned: {total_scanned:,}, Found: {len(records_to_update):,}", end="\r"
        )

    print(
        f"\n✓ Scan complete. Total records matching criteria: {len(records_to_update):,}"
    )
    return records_to_update


def update_single_record(table, key):
    """Update a single record's field."""
    try:
        if DRY_RUN:
            return True, key, "DRY RUN - No change made"

        table.update_item(
            Key=key,
            UpdateExpression=f"SET {FIELD_TO_UPDATE} = :val",
            ExpressionAttributeValues={":val": NEW_VALUE_TO_SET},
            ConditionExpression=Attr(FIELD_TO_UPDATE).eq(
                CURRENT_VALUE_TO_FIND
            ),  # Safety check
        )
        return True, key, "Updated"
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False, key, "Skipped - value already changed"
    except Exception as e:
        return False, key, str(e)


def batch_update_records(records, table):
    """
    Update records in batches using parallel execution.
    """
    total_records = len(records)
    total_batches = (total_records + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"\n{'='*60}")
    if DRY_RUN:
        print("🔍 DRY RUN MODE - No actual changes will be made")
    print(
        f"Processing {total_records:,} records in {total_batches} batches of {BATCH_SIZE}"
    )
    print(f"{'='*60}")

    success_count = 0
    skip_count = 0
    error_count = 0
    errors = []

    overall_start = time.time()

    for batch_num in range(total_batches):
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, total_records)
        batch = records[start_idx:end_idx]

        print(
            f"\nBatch {batch_num + 1}/{total_batches}: Processing records {start_idx + 1:,} to {end_idx:,}..."
        )
        batch_start = time.time()

        batch_success = 0
        batch_skip = 0
        batch_error = 0

        # Parallel updates within the batch
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}

            for record in batch:
                # Build the key based on table schema
                if SORT_KEY:
                    key = {
                        PARTITION_KEY: record[PARTITION_KEY],
                        SORT_KEY: record[SORT_KEY],
                    }
                else:
                    key = {PARTITION_KEY: record[PARTITION_KEY]}

                future = executor.submit(update_single_record, table, key)
                futures[future] = key

            for future in as_completed(futures):
                success, key, message = future.result()
                if success:
                    if "DRY RUN" in message or "Updated" in message:
                        success_count += 1
                        batch_success += 1
                    else:
                        skip_count += 1
                        batch_skip += 1
                else:
                    if "Skipped" in message:
                        skip_count += 1
                        batch_skip += 1
                    else:
                        error_count += 1
                        batch_error += 1
                        errors.append(f"{key}: {message}")

        batch_time = time.time() - batch_start
        print(
            f"  ✓ Batch complete in {batch_time:.2f}s | Updated: {batch_success}, Skipped: {batch_skip}, Errors: {batch_error}"
        )

        # Delay between batches to avoid throttling
        if batch_num < total_batches - 1 and DELAY_BETWEEN_BATCHES > 0:
            time.sleep(DELAY_BETWEEN_BATCHES)

    total_time = time.time() - overall_start
    return success_count, skip_count, error_count, errors, total_time


def print_sample_records(table, records, count=5):
    """Print sample records that will be updated."""
    print(f"\nSample records to be updated (showing first {count}):")
    print("-" * 60)

    for i, record in enumerate(records[:count]):
        if SORT_KEY:
            key = {PARTITION_KEY: record[PARTITION_KEY], SORT_KEY: record[SORT_KEY]}
        else:
            key = {PARTITION_KEY: record[PARTITION_KEY]}

        try:
            response = table.get_item(Key=key)
            item = response.get("Item", {})
            print(f"\n  Record {i + 1}:")
            print(f"    {PARTITION_KEY}: {item.get(PARTITION_KEY, 'N/A')}")
            if SORT_KEY:
                print(f"    {SORT_KEY}: {item.get(SORT_KEY, 'N/A')}")
            print(f"    Current {FIELD_TO_UPDATE}: {item.get(FIELD_TO_UPDATE, 'N/A')}")
            print(f"    Will change to: {NEW_VALUE_TO_SET}")
        except Exception as e:
            print(f"  Record {i + 1}: Error fetching details - {e}")

    print("-" * 60)


def main():
    """Main entry point."""
    config = get_active_config()

    # Header
    print("\n" + "=" * 70)
    print("DynamoDB Batch Update Script")
    print("=" * 70)
    print(f"  Environment:    {config['DESCRIPTION']}")
    print(f"  Table:          {config['TABLE_NAME']}")
    print(f"  Region:         {config['AWS_REGION']}")
    print(f"  AWS Profile:    {config.get('AWS_PROFILE') or 'default'}")
    print(f"  Field:          {FIELD_TO_UPDATE}")
    print(f"  Find value:     '{CURRENT_VALUE_TO_FIND}'")
    print(f"  Replace with:   '{NEW_VALUE_TO_SET}'")
    print(f"  Batch size:     {BATCH_SIZE}")
    print(
        f"  DRY RUN:        {'YES (no changes will be made)' if DRY_RUN else 'NO (changes WILL be made)'}"
    )
    print("=" * 70)

    # Safety warning for PROD
    if ENVIRONMENT.upper() == "PROD":
        print("\n" + "!" * 70)
        print("  ⚠️  WARNING: You are about to modify PRODUCTION data!")
        print("!" * 70)
        if not DRY_RUN:
            confirm1 = input(
                "\n  Type 'PROD' to confirm you want to modify production: "
            )
            if confirm1 != "PROD":
                print("  Cancelled - confirmation text did not match.")
                return

    # Initialize DynamoDB
    try:
        print("\nConnecting to DynamoDB...")
        dynamodb = get_dynamodb_resource(config)
        table = dynamodb.Table(config["TABLE_NAME"])

        # Verify table exists
        table.load()
        print(f"✓ Connected to table: {config['TABLE_NAME']}")
        print(f"  Item count (approximate): {table.item_count:,}")
    except Exception as e:
        print(f"\n✗ Error connecting to DynamoDB: {e}")
        print("\nTroubleshooting:")
        print("  1. Verify AWS credentials are configured")
        print("  2. Check the table name is correct")
        print("  3. Verify you have access to this table")
        return

    # Step 1: Find records to update
    records = scan_records_to_update(table)

    if not records:
        print("\n✗ No records found matching the filter criteria.")
        print("  Check your CURRENT_VALUE_TO_FIND and ADDITIONAL_FILTER settings.")
        return

    # Step 2: Show sample records
    print_sample_records(table, records)

    # Step 3: Confirm before proceeding
    print(f"\n{'='*60}")
    if DRY_RUN:
        print("This is a DRY RUN - no changes will be made.")
        confirm = input("Proceed with dry run? (yes/no): ")
    else:
        print(
            f"⚠️  This will UPDATE {len(records):,} records in {config['DESCRIPTION']}"
        )
        confirm = input("Type 'yes' to proceed with updates: ")

    if confirm.lower() != "yes":
        print("Cancelled by user.")
        return

    # Step 4: Perform batch update
    start_time = datetime.now()
    print(f"\nStarted: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    success, skipped, errors_count, error_details, elapsed = batch_update_records(
        records, table
    )

    end_time = datetime.now()

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Environment:      {config['DESCRIPTION']}")
    print(f"  Table:            {config['TABLE_NAME']}")
    print(f"  DRY RUN:          {'Yes' if DRY_RUN else 'No'}")
    print(f"  Total Processed:  {len(records):,}")
    print(f"  Successful:       {success:,}")
    print(f"  Skipped:          {skipped:,}")
    print(f"  Errors:           {errors_count:,}")
    print(f"  Time:             {elapsed:.2f}s")
    print(f"  Started:          {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Finished:         {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

    if error_details:
        print(f"\n{'='*60}")
        print("ERRORS (first 10):")
        print(f"{'='*60}")
        for err in error_details[:10]:
            print(f"  ✗ {err}")
        if len(error_details) > 10:
            print(f"  ... and {len(error_details) - 10} more errors")

    if DRY_RUN:
        print(f"\n{'='*70}")
        print("  ℹ️  This was a DRY RUN - no actual changes were made.")
        print("  To perform actual updates, set DRY_RUN = False and run again.")
        print(f"{'='*70}")

    print("\n✓ Script completed.")


if __name__ == "__main__":
    main()
