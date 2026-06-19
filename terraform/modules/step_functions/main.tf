locals {
  name_prefix            = "${var.project_name}-${var.environment}"
  state_machine_name     = "${local.name_prefix}-sentiment-pipeline"
  athena_output_location = "s3://${var.data_product_bucket_id}/${var.athena_results_prefix}/"
  athena_results_arn     = "${var.data_product_bucket_arn}/${var.athena_results_prefix}/*"
  log_group_name         = "/aws/vendedlogs/states/${local.state_machine_name}"

  definition = templatefile("${path.module}/state_machine.asl.json", {
    job_clean_name              = var.job_clean_name
    job_agg_name                = var.job_agg_name
    crawler_name                = var.crawler_name
    customer_sentiment_database = var.customer_sentiment_database
    customer_sentiment_table    = var.customer_sentiment_table
    athena_output_location      = local.athena_output_location
  })

  default_input = {
    dt              = "YYYY-MM-DD"
    bucket_raw      = var.raw_bucket_id
    bucket_trusted  = var.trusted_bucket_id
    bucket_product  = var.data_product_bucket_id
  }
}

# ---------------------------------------------------------------------------
# Lake Formation: grant SFN role access to validate customer_sentiment via Athena.
# ---------------------------------------------------------------------------
resource "aws_lakeformation_permissions" "sfn_customer_database" {
  principal   = var.sfn_role_arn
  permissions = ["DESCRIBE"]

  database {
    name = var.customer_sentiment_database
  }
}

resource "aws_lakeformation_permissions" "sfn_customer_tables" {
  principal   = var.sfn_role_arn
  permissions = ["SELECT"]

  table {
    database_name = var.customer_sentiment_database
    wildcard      = true
  }
}

resource "aws_lakeformation_permissions" "sfn_data_product_location" {
  principal   = var.sfn_role_arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = var.data_product_bucket_arn
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
    sid       = "ReadDataProductBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.data_product_bucket_arn]
  }

  statement {
    sid       = "ReadDataProductObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.data_product_bucket_arn}/*"]
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
    aws_lakeformation_permissions.sfn_customer_tables,
  ]
}
