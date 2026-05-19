from pyspark.sql import SparkSession
from pyspark.sql.functions import md5, concat_ws
from datetime import datetime
import os

spark = SparkSession.builder \
    .appName("CSV to MD5 Hash") \
    .getOrCreate()
input_folder_path = "C:\\GitHub\\Sample_PyPrj\\inputfiles\\"
ouput_folder_path = "C:\\GitHub\\Sample_PyPrj\\outputfiles\\"

for filename in os.listdir(input_folder_path):
    if filename.endswith(".csv"):        
        csv_file_path = os.path.join(input_folder_path, filename)

        #csv_file_path = "edfx-24714_Landing_QA.csv"
        df = spark.read.csv(csv_file_path, inferSchema=True, header=True)

        df_with_hash = df.withColumn('peer_hash_id', md5(concat_ws("", df['peer_group_id'], df['variable'], df['metric'],df['metric_value_date'])))

        ouputfile =f"{ouput_folder_path}{filename}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"
        df_with_hash.write.csv(ouputfile, header=True)

        break
