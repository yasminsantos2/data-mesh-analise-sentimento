data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name_suffix   = var.bucket_suffix != "" ? "-${var.bucket_suffix}" : ""
  bucket_name   = "${var.project_name}-${var.environment}-athena-results${local.name_suffix}"
  results_uri   = "s3://${aws_s3_bucket.athena_results.bucket}/${var.results_prefix}/"
  results_arn   = "${aws_s3_bucket.athena_results.arn}/${var.results_prefix}/*"
  views_content = replace(file("${path.module}/views.sql"), "\r\n", "\n")
  view_names    = ["vw_sentiment_by_age", "vw_sentiment_by_dept", "vw_daily_trend"]
  view_parts    = [for p in split("-- @query ", local.views_content) : trimspace(p) if trimspace(p) != ""]
  view_queries = {
    for part in local.view_parts :
    element(split("\n", part), 0) => trimspace(join("\n", slice(split("\n", part), 1, length(split("\n", part)))))
  }
}

# ---------------------------------------------------------------------------
# Dedicated bucket for Marketing Athena query results.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "athena_results" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy

  tags = merge(var.tags, {
    Name    = local.bucket_name
    Purpose = "athena-marketing-results"
  })
}

resource "aws_s3_bucket_versioning" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------------------------------------------------------
# Marketing workgroup — cost guardrail + enforced result location.
# ---------------------------------------------------------------------------
resource "aws_athena_workgroup" "marketing" {
  name = var.workgroup_name

  configuration {
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff_per_query
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = local.results_uri
    }
  }

  tags = var.tags
}

resource "aws_athena_named_query" "views" {
  for_each = local.view_queries

  name        = each.key
  workgroup   = aws_athena_workgroup.marketing.name
  database    = var.customer_sentiment_database
  description = "Marketing analytical view: ${each.key}"
  query       = each.value
}

# ---------------------------------------------------------------------------
# athena_role: scoped to marketing_wg only (no other workgroups).
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "marketing_athena" {
  statement {
    sid    = "AthenaMarketingWorkgroup"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetNamedQuery",
      "athena:ListNamedQueries",
      "athena:BatchGetNamedQuery",
      "athena:GetWorkGroup",
      "athena:ListQueryExecutions",
    ]
    resources = [
      "arn:aws:athena:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workgroup/${var.workgroup_name}",
    ]
  }

  statement {
    sid       = "AthenaResultsBucketList"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.athena_results.arn]
  }

  statement {
    sid       = "AthenaResultsBucketWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [local.results_arn]
  }
}

resource "aws_iam_role_policy" "marketing_athena" {
  name   = "${var.project_name}-${var.environment}-marketing-athena-policy"
  role   = var.athena_role_name
  policy = data.aws_iam_policy_document.marketing_athena.json
}
