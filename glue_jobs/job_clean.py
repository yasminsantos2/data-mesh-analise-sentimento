"""Glue Job: job_clean.

Reads raw review CSVs, removes rows with null review_text, standardizes column
names to snake_case, derives the age_band column, and writes snappy-compressed
Parquet to the trusted layer.

Args: --dt --bucket_raw --bucket_trusted
"""
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.functions import col, length, trim
from pyspark.sql.types import StringType

from transforms import age_band, to_snake_case

args = getResolvedOptions(sys.argv, ["JOB_NAME", "dt", "bucket_raw", "bucket_trusted"])

dt = args["dt"]
bucket_raw = args["bucket_raw"]
bucket_trusted = args["bucket_trusted"]

sc = SparkContext.getOrCreate()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

age_band_udf = glueContext.spark_session.udf.register("age_band", age_band, StringType())

input_path = f"s3://{bucket_raw}/reviews/dt={dt}/"
output_path = f"s3://{bucket_trusted}/reviews_clean/dt={dt}/"

# Read raw CSV via GlueContext.
dyf = glueContext.create_dynamic_frame.from_options(
    connection_type="s3",
    connection_options={"paths": [input_path], "recurse": True},
    format="csv",
    format_options={"withHeader": True, "separator": ","},
)
df = dyf.toDF()

# Standardize column names to snake_case.
for c in df.columns:
    df = df.withColumnRenamed(c, to_snake_case(c))

# Drop rows with null/empty review_text.
df = df.filter(col("review_text").isNotNull() & (length(trim(col("review_text"))) > 0))

# Derive age_band from age.
df = df.withColumn("age_band", age_band_udf(col("age")))

# Write snappy Parquet to trusted. Overwrite makes reprocessing the same dt
# idempotent.
(
    df.write.mode("overwrite")
    .option("compression", "snappy")
    .parquet(output_path)
)

job.commit()
