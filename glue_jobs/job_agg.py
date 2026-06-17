"""Glue Job: job_agg.

Reads cleaned reviews from the trusted layer, classifies sentiment, aggregates
by (age_band, department_name, sentiment) and writes the data product Parquet
to the data-product layer.

Args: --dt --bucket_trusted --bucket_product
"""
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.functions import avg, col, count, lit, round as spark_round
from pyspark.sql.types import StringType

from transforms import sentiment

args = getResolvedOptions(sys.argv, ["JOB_NAME", "dt", "bucket_trusted", "bucket_product"])

dt = args["dt"]
bucket_trusted = args["bucket_trusted"]
bucket_product = args["bucket_product"]

sc = SparkContext.getOrCreate()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

sentiment_udf = glueContext.spark_session.udf.register("sentiment", sentiment, StringType())

input_path = f"s3://{bucket_trusted}/reviews_clean/dt={dt}/"
output_path = f"s3://{bucket_product}/customer_sentiment_by_age/dt={dt}/"

df = spark.read.parquet(input_path)

# Classify sentiment from rating + recommended_ind.
df = df.withColumn("sentiment", sentiment_udf(col("rating"), col("recommended_ind")))

# Exclude rows that would introduce nulls in the aggregation keys.
df = df.filter(col("age_band").isNotNull() & col("department_name").isNotNull())

agg = (
    df.groupBy("age_band", "department_name", "sentiment")
    .agg(
        count(lit(1)).cast("int").alias("review_count"),
        spark_round(avg(col("rating").cast("double")), 2).alias("avg_rating"),
    )
    .select(
        "age_band",
        "department_name",
        "sentiment",
        "review_count",
        "avg_rating",
    )
)

# dt is a Hive partition key (path dt=YYYY-MM-DD/), not a physical Parquet
# column. Writing dt inside the file makes the crawler duplicate it in the Glue
# catalog alongside the partition key, breaking Athena queries.

# Overwrite makes reprocessing the same dt idempotent.
agg.write.mode("overwrite").parquet(output_path)

job.commit()
