from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.functions import md5, concat_ws

# Initialize SparkSession
spark = SparkSession.builder \
    .appName("Process Results DataFrame") \
    .getOrCreate()

# Path to the CSV file (update this to your file's path)
csv_file_path = 'C:\\Github\\MyUtilities\\Day2Day_Utillites\\inputfiles\\edfx-24714_Landing_QA.csv'

# Load CSV into Spark DataFrame
results_df = spark.read.csv(csv_file_path, inferSchema=True, header=True)


# Step 1: Modify 'metric_value_date' based on specific conditions
# results_df = results_df.withColumn(
#     'metric_value_date',
#     F.when(F.col("metric_value_date").endswith('02'), F.regexp_replace(F.col("metric_value_date"), r'(02$)', '01'))
#      .when(F.col("metric_value_date").endswith('03'), F.regexp_replace(F.col("metric_value_date"), r'(03$)', '01'))
#      .otherwise(F.col("metric_value_date"))
# )

# # Print schema and distinct values for `metric_value_date`
# print(" results_df ")
# results_df.printSchema()
# results_df.select("metric_value_date").distinct().orderBy(F.col("metric_value_date").desc()).show(10, False)

# Step 2: Create an MD5 hash value for extrapolations
# Create a hash column 'peer_hash_id' by concatenating specified columns
df = results_df

results_df_hash = df.withColumn('peer_hash_id2', md5(concat_ws("", df['peer_group_id'], df['variable'], df['metric'],df['metric_value_date'])))

# Select only the required columns
results_df_hash = results_df_hash.select(
    'peer_hash_id',
    'peer_hash_id2',
    'peer_group_id',
    'variable',
    'variable_unit',
    'variable_currency',
    'metric',
    'metric_value',
    'metric_value_date',
    'snapshot_datetime'
)

# Show the first 100 rows (without truncating columns)
results_df_hash.show(100, False)

# Step 3: Write the DataFrame to a CSV file with the specified options
# Define parameters for writing
params = {
    'output_mode': 'overwrite',  # Replace with 'append' or 'overwrite' as needed
}