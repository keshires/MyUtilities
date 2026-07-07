import pandas as pd
import sys
import os
import logging
import json
from pyspark.sql import functions as F
from pyspark.sql.functions import md5, concat_ws, col
from pyspark.sql import SparkSession
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# Step 1: Read the CSV file
file_path = 'C:\\Github\\MyUtilities\\Day2Day_Utillites\\inputfiles\\edfx-24714_Landing_QA.csv'  # Replace with your CSV file path
results_df = pd.read_csv(file_path)

# Create a Spark session
spark = SparkSession.builder.appName("WithColumnExample").getOrCreate()
df = results_df 

results_df_hash = df.withColumn('peer_hash_id', md5(concat_ws("", df['peer_group_id'], df['variable'], df['metric'],df['metric_value_date'])))
results_df_hash = results_df_hash.select('peer_hash_id','peer_group_id','variable','variable_unit','variable_currency','metric','metric_value','metric_value_date','snapshot_datetime')

#df["peer_hash_id"] = md5(concat_ws("", df['peer_group_id'], df['variable'], df['metric'],df['metric_value_date']))
#results_df_hash = results_df_hash.select('peer_hash_id','peer_group_id','variable','variable_unit','variable_currency','metric','metric_value','metric_value_date','snapshot_datetime')
df.show(100,False)
df.write.mode('append') \
    .option("header", True) \
    .option("escape", '\"') \
    .option("quote", '\"') \
    .option("compression", "gzip") \
    .option("maxRecordsPerFile", 1000) \
    .partitionBy(['snapshot_datetime']) \
    .csv("C:\\Github\\MyUtilities\\Day2Day_Utillites\\inputfiles\\edfx-24714_Landing_QA_Output.csv")


# Step 2: Add a new column
# Example: Adding a column called 'NewColumn' with default value 0
df['NewColumn'] = 0


# Step 3: Save the updated CSV file
output_file_path = 'updated_file.csv'  # Specify the path for the updated CSV file
df.to_csv(output_file_path, index=False)

print(f"New column added and saved to {output_file_path}")