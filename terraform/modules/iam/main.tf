data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# Glue role
#   - READ  on the raw bucket
#   - WRITE on the trusted bucket
#   - NO access to the data-product bucket (enforced by omission)
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "glue_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue" {
  name               = "${local.name_prefix}-glue-role"
  description        = "Glue ETL role: reads raw, writes trusted. No data-product access."
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "glue" {
  # List raw + trusted buckets.
  statement {
    sid       = "ListRawAndTrusted"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.raw_bucket_arn, var.trusted_bucket_arn]
  }

  # Read objects from raw.
  statement {
    sid       = "ReadRaw"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.raw_bucket_arn}/*"]
  }

  # Read/write/delete objects in trusted.
  statement {
    sid       = "WriteTrusted"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.trusted_bucket_arn}/*"]
  }

  # Glue needs to write its own CloudWatch logs.
  statement {
    sid    = "GlueLogging"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:/aws-glue/*"]
  }
}

resource "aws_iam_role_policy" "glue" {
  name   = "${local.name_prefix}-glue-policy"
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue.json
}

# Managed policy required by the Glue service for job execution internals.
resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# ---------------------------------------------------------------------------
# Step Functions role
#   - Invoke and monitor Glue Jobs and Crawlers
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "sfn_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name_prefix}-sfn-role"
  description        = "Step Functions role: starts and monitors Glue Jobs and Crawlers."
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "sfn" {
  # Run and monitor Glue jobs, scoped to project-named jobs.
  statement {
    sid    = "RunGlueJobs"
    effect = "Allow"
    actions = [
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns",
      "glue:BatchStopJobRun",
    ]
    resources = ["arn:aws:glue:*:${data.aws_caller_identity.current.account_id}:job/${local.name_prefix}-*"]
  }

  # Run and monitor Glue crawlers, scoped to project-named crawlers.
  statement {
    sid    = "RunGlueCrawlers"
    effect = "Allow"
    actions = [
      "glue:StartCrawler",
      "glue:GetCrawler",
      "glue:GetCrawlerMetrics",
    ]
    resources = ["arn:aws:glue:*:${data.aws_caller_identity.current.account_id}:crawler/${local.name_prefix}-*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "${local.name_prefix}-sfn-policy"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

# ---------------------------------------------------------------------------
# Athena role
#   - READ on the data-product bucket (Lake Formation gates table access)
#   - Athena workgroup + results bucket permissions are attached by the athena module
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "athena_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    # Assumed by principals (users/services) within this account that run queries.
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "athena" {
  name               = "${local.name_prefix}-athena-role"
  description        = "Athena role: reads data-product and writes query results."
  assume_role_policy = data.aws_iam_policy_document.athena_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "athena" {
  # Read-only Glue Data Catalog access used by Athena to resolve tables.
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

  # Required so Athena can read data managed by Lake Formation. Lake Formation
  # still gates which databases/tables are accessible via its own permissions.
  statement {
    sid       = "LakeFormationDataAccess"
    effect    = "Allow"
    actions   = ["lakeformation:GetDataAccess"]
    resources = ["*"]
  }

  # List the data-product bucket and read its objects.
  statement {
    sid       = "ReadDataProduct"
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
}

resource "aws_iam_role_policy" "athena" {
  name   = "${local.name_prefix}-athena-policy"
  role   = aws_iam_role.athena.id
  policy = data.aws_iam_policy_document.athena.json
}
