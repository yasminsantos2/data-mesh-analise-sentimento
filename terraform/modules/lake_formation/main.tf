data "aws_caller_identity" "current" {}

locals {
  # Derive bucket names from their ARNs (arn:aws:s3:::<name>).
  trusted_bucket_name      = replace(var.trusted_bucket_arn, "arn:aws:s3:::", "")
  data_product_bucket_name = replace(var.data_product_bucket_arn, "arn:aws:s3:::", "")

  # The executing principal is kept as an admin alongside glue_role so that
  # Terraform itself can keep managing Lake Formation permissions. Removing it
  # would lock Terraform out of subsequent LF API calls.
  admin_arns = distinct(concat(
    [var.glue_role_arn, data.aws_caller_identity.current.arn],
    var.extra_admin_arns,
  ))
}

# ---------------------------------------------------------------------------
# 1. Data lake settings
#    - glue_role (and the executor) are the Lake Formation admins
#    - Omitting create_database_default_permissions and
#      create_table_default_permissions is equivalent to sending an empty list,
#      which revokes the default Super grant from IAMAllowedPrincipals on new
#      databases and tables.
# ---------------------------------------------------------------------------
resource "aws_lakeformation_data_lake_settings" "this" {
  admins = local.admin_arns
}

# ---------------------------------------------------------------------------
# 2. Register the trusted and data-product buckets as data lake locations.
# ---------------------------------------------------------------------------
resource "aws_lakeformation_resource" "trusted" {
  arn                     = var.trusted_bucket_arn
  use_service_linked_role = true
}

resource "aws_lakeformation_resource" "data_product" {
  arn                     = var.data_product_bucket_arn
  use_service_linked_role = true
}

# ---------------------------------------------------------------------------
# 3 + 4. Glue Catalog databases.
#    They depend on the data lake settings so that, by the time they are
#    created, default IAMAllowedPrincipals grants are already disabled.
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_database" "reviews_trusted" {
  name         = var.reviews_trusted_db_name
  description  = "Trusted (silver) layer database for curated review data."
  location_uri = "s3://${local.trusted_bucket_name}/${var.reviews_trusted_db_name}/"

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

resource "aws_glue_catalog_database" "customer_sentiment" {
  name         = var.customer_sentiment_db_name
  description  = "Data-product (gold) layer database exposing customer sentiment products."
  location_uri = "s3://${local.data_product_bucket_name}/${var.customer_sentiment_db_name}/"

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# ---------------------------------------------------------------------------
# 5. Lake Formation permissions
# ---------------------------------------------------------------------------

# glue_role: ALL on both databases (create/alter/drop tables, etc.).
resource "aws_lakeformation_permissions" "glue_reviews_db" {
  principal   = var.glue_role_arn
  permissions = ["ALL"]

  database {
    name = aws_glue_catalog_database.reviews_trusted.name
  }

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

resource "aws_lakeformation_permissions" "glue_customer_db" {
  principal   = var.glue_role_arn
  permissions = ["ALL"]

  database {
    name = aws_glue_catalog_database.customer_sentiment.name
  }

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# glue_role: ALL on every table (current and future) of both databases so it
# can write data products without per-table grants.
resource "aws_lakeformation_permissions" "glue_reviews_tables" {
  principal   = var.glue_role_arn
  permissions = ["ALL"]

  table {
    database_name = aws_glue_catalog_database.reviews_trusted.name
    wildcard      = true
  }

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

resource "aws_lakeformation_permissions" "glue_customer_tables" {
  principal   = var.glue_role_arn
  permissions = ["ALL"]

  table {
    database_name = aws_glue_catalog_database.customer_sentiment.name
    wildcard      = true
  }

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# athena_role: DESCRIBE on the customer_sentiment database so Athena can list
# it, plus SELECT on all of its tables.
resource "aws_lakeformation_permissions" "athena_customer_describe" {
  principal   = var.athena_role_arn
  permissions = ["DESCRIBE"]

  database {
    name = aws_glue_catalog_database.customer_sentiment.name
  }

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

resource "aws_lakeformation_permissions" "athena_customer_select" {
  principal   = var.athena_role_arn
  permissions = ["SELECT"]

  table {
    database_name = aws_glue_catalog_database.customer_sentiment.name
    wildcard      = true
  }

  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# athena_role: DENIED on reviews_trusted.
# Lake Formation is grant-based and default permissions are disabled, so NOT
# granting any permission on reviews_trusted means athena_role is implicitly
# denied (Athena/Glue return AccessDeniedException). No grant resource is
# created here on purpose.

# ---------------------------------------------------------------------------
# 6. Data-product table: customer_sentiment_by_age (Parquet, partitioned by dt)
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_table" "customer_sentiment_by_age" {
  name          = "customer_sentiment_by_age"
  database_name = aws_glue_catalog_database.customer_sentiment.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL       = "TRUE"
    classification = "parquet"
    owner          = "data-team"
    sla            = "30min"
    domain         = "marketing"
  }

  partition_keys {
    name = "dt"
    type = "date"
  }

  storage_descriptor {
    location      = "s3://${local.data_product_bucket_name}/customer_sentiment_by_age/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "parquet"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"

      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "age_band"
      type = "string"
    }
    columns {
      name = "department_name"
      type = "string"
    }
    columns {
      name = "sentiment"
      type = "string"
    }
    columns {
      name = "review_count"
      type = "int"
    }
    columns {
      name = "avg_rating"
      type = "double"
    }
  }
}
