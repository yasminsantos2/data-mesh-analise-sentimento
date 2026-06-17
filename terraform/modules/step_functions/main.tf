locals {
  name_prefix            = "${var.project_name}-${var.environment}"
  state_machine_name     = "${local.name_prefix}-sentiment-pipeline"
  athena_output_location = "s3://${var.data_product_bucket_id}/${var.athena_results_prefix}/"
  athena_results_arn     = "${var.data_product_bucket_arn}/${var.athena_results_prefix}/*"
  raw_reviews_location   = "s3://${var.raw_bucket_id}/reviews/"
  log_group_name         = "/aws/vendedlogs/states/${local.state_machine_name}"

  definition = templatefile(var.definition_source_path, {
    job_clean_name         = var.job_clean_name
    job_agg_name           = var.job_agg_name
    crawler_name           = var.crawler_name
    raw_bucket             = var.raw_bucket_id
    trusted_bucket         = var.trusted_bucket_id
    data_product_bucket    = var.data_product_bucket_id
    raw_database           = var.raw_database_name
    raw_table              = var.raw_table_name
    athena_output_location = local.athena_output_location
  })
}

# ---------------------------------------------------------------------------
# Glue Catalog: external table over raw CSV with partition projection so
# Athena can COUNT rows for a given dt without registering 235 partitions.
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_database" "reviews_raw" {
  name         = var.raw_database_name
  description  = "Raw (bronze) layer database for ingested review CSV batches."
  location_uri = local.raw_reviews_location
}

resource "aws_glue_catalog_table" "reviews" {
  name          = var.raw_table_name
  database_name = aws_glue_catalog_database.reviews_raw.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"                = "csv"
    "skip.header.line.count"        = "1"
    "projection.enabled"            = "true"
    "projection.dt.type"            = "date"
    "projection.dt.range"           = "2024-01-01,2024-12-31"
    "projection.dt.format"          = "yyyy-MM-dd"
    "storage.location.template"     = "${local.raw_reviews_location}dt=$${dt}/"
  }

  storage_descriptor {
    location      = local.raw_reviews_location
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "OpenCSVSerde"
      serialization_library = "org.apache.hadoop.hive.serde2.OpenCSVSerde"
      parameters = {
        "separatorChar" = ","
        "quoteChar"     = "\""
        "escapeChar"    = "\\"
      }
    }

    columns {
      name = "clothing_id"
      type = "int"
    }
    columns {
      name = "age"
      type = "int"
    }
    columns {
      name = "title"
      type = "string"
    }
    columns {
      name = "review_text"
      type = "string"
    }
    columns {
      name = "rating"
      type = "int"
    }
    columns {
      name = "recommended_ind"
      type = "int"
    }
    columns {
      name = "division_name"
      type = "string"
    }
    columns {
      name = "department_name"
      type = "string"
    }
    columns {
      name = "class_name"
      type = "string"
    }
  }

  partition_keys {
    name = "dt"
    type = "string"
  }
}

# ---------------------------------------------------------------------------
# Lake Formation: register raw location and grant the SFN role SELECT.
# ---------------------------------------------------------------------------
resource "aws_lakeformation_resource" "raw" {
  arn                     = var.raw_bucket_arn
  use_service_linked_role = true
}

resource "aws_lakeformation_permissions" "sfn_raw_location" {
  principal   = var.sfn_role_arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = var.raw_bucket_arn
  }

  depends_on = [aws_lakeformation_resource.raw]
}

resource "aws_lakeformation_permissions" "sfn_raw_database" {
  principal   = var.sfn_role_arn
  permissions = ["DESCRIBE"]

  database {
    name = aws_glue_catalog_database.reviews_raw.name
  }
}

resource "aws_lakeformation_permissions" "sfn_raw_table" {
  principal   = var.sfn_role_arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = aws_glue_catalog_database.reviews_raw.name
    name          = aws_glue_catalog_table.reviews.name
  }
}

# ---------------------------------------------------------------------------
# Extra IAM permissions for the existing SFN role (Athena + S3 + logs).
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "sfn_pipeline" {
  statement {
    sid    = "AthenaQueries"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetWorkGroup",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GlueCatalogRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "LakeFormationDataAccess"
    effect    = "Allow"
    actions   = ["lakeformation:GetDataAccess"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadRawBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.raw_bucket_arn]
  }

  statement {
    sid       = "ReadRawObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.raw_bucket_arn}/*"]
  }

  statement {
    sid       = "AthenaResultsBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.data_product_bucket_arn]
  }

  statement {
    sid       = "AthenaResultsObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [local.athena_results_arn]
  }

  statement {
    sid    = "StepFunctionsLogging"
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn_pipeline" {
  name   = "${local.name_prefix}-sfn-pipeline-policy"
  role   = var.sfn_role_name
  policy = data.aws_iam_policy_document.sfn_pipeline.json
}

# ---------------------------------------------------------------------------
# CloudWatch Logs for Step Functions execution history.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "sfn" {
  name              = local.log_group_name
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_cloudwatch_log_resource_policy" "sfn" {
  policy_name = "${local.name_prefix}-sfn-log-policy"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "states.${data.aws_region.current.name}.amazonaws.com"
      }
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "${aws_cloudwatch_log_group.sfn.arn}:*"
      Condition = {
        ArnLike = {
          "aws:SourceArn" = "arn:aws:states:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.state_machine_name}"
        }
      }
    }]
  })
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------
resource "aws_sfn_state_machine" "pipeline" {
  name     = local.state_machine_name
  role_arn = var.sfn_role_arn
  type     = "STANDARD"

  definition = local.definition

  logging_configuration {
    level                  = "ALL"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy.sfn_pipeline,
    aws_cloudwatch_log_resource_policy.sfn,
    aws_lakeformation_permissions.sfn_raw_table,
  ]
}
