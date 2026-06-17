locals {
  name_prefix = "${var.project_name}-${var.environment}"

  scripts_base   = "s3://${var.trusted_bucket_id}/${var.scripts_prefix}"
  transforms_key = "${var.scripts_prefix}/transforms.py"
  clean_key      = "${var.scripts_prefix}/job_clean.py"
  agg_key        = "${var.scripts_prefix}/job_agg.py"
}

# ---------------------------------------------------------------------------
# Upload the PySpark scripts to the trusted bucket (readable by the job roles).
# ---------------------------------------------------------------------------
resource "aws_s3_object" "transforms" {
  bucket = var.trusted_bucket_id
  key    = local.transforms_key
  source = "${var.scripts_source_dir}/transforms.py"
  etag   = filemd5("${var.scripts_source_dir}/transforms.py")
}

resource "aws_s3_object" "job_clean" {
  bucket = var.trusted_bucket_id
  key    = local.clean_key
  source = "${var.scripts_source_dir}/job_clean.py"
  etag   = filemd5("${var.scripts_source_dir}/job_clean.py")
}

resource "aws_s3_object" "job_agg" {
  bucket = var.trusted_bucket_id
  key    = local.agg_key
  source = "${var.scripts_source_dir}/job_agg.py"
  etag   = filemd5("${var.scripts_source_dir}/job_agg.py")
}

# ---------------------------------------------------------------------------
# Dedicated role for job_agg: reads trusted, writes data-product.
# (glue_role from S1-01 deliberately has NO data-product access, so the
#  aggregation job needs its own least-privilege role.)
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

resource "aws_iam_role" "agg" {
  name               = "${local.name_prefix}-glue-agg-role"
  description        = "Glue job_agg role: reads trusted, writes data-product."
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "agg" {
  statement {
    sid       = "ReadTrusted"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.trusted_bucket_arn]
  }
  statement {
    sid       = "ReadTrustedObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.trusted_bucket_arn}/*"]
  }
  statement {
    sid       = "WriteDataProduct"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.data_product_bucket_arn]
  }
  statement {
    sid       = "WriteDataProductObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.data_product_bucket_arn}/*"]
  }
  statement {
    sid       = "Logging"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:/aws-glue/*"]
  }
}

resource "aws_iam_role_policy" "agg" {
  name   = "${local.name_prefix}-glue-agg-policy"
  role   = aws_iam_role.agg.id
  policy = data.aws_iam_policy_document.agg.json
}

resource "aws_iam_role_policy_attachment" "agg_service" {
  role       = aws_iam_role.agg.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# ---------------------------------------------------------------------------
# Dedicated role for the crawler: reads data-product + registers tables via
# Lake Formation in the customer_sentiment database.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "crawler" {
  name               = "${local.name_prefix}-glue-crawler-role"
  description        = "Glue crawler role for the data-product database."
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "crawler" {
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
  statement {
    sid       = "LakeFormationDataAccess"
    effect    = "Allow"
    actions   = ["lakeformation:GetDataAccess"]
    resources = ["*"]
  }
  statement {
    sid       = "Logging"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:/aws-glue/*"]
  }
}

resource "aws_iam_role_policy" "crawler" {
  name   = "${local.name_prefix}-glue-crawler-policy"
  role   = aws_iam_role.crawler.id
  policy = data.aws_iam_policy_document.crawler.json
}

resource "aws_iam_role_policy_attachment" "crawler_service" {
  role       = aws_iam_role.crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# Lake Formation grants so the crawler can read the registered location and
# create/update tables in the customer_sentiment database.
resource "aws_lakeformation_permissions" "crawler_location" {
  principal   = aws_iam_role.crawler.arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = var.data_product_bucket_arn
  }
}

resource "aws_lakeformation_permissions" "crawler_database" {
  principal   = aws_iam_role.crawler.arn
  permissions = ["CREATE_TABLE", "ALTER", "DESCRIBE"]

  database {
    name = var.customer_sentiment_db_name
  }
}

resource "aws_lakeformation_permissions" "crawler_tables" {
  principal   = aws_iam_role.crawler.arn
  permissions = ["ALL"]

  table {
    database_name = var.customer_sentiment_db_name
    wildcard      = true
  }
}

# ---------------------------------------------------------------------------
# Glue Jobs
# ---------------------------------------------------------------------------
resource "aws_glue_job" "clean" {
  name              = "${local.name_prefix}-job-clean"
  role_arn          = var.glue_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.job_timeout_minutes

  command {
    name            = "glueetl"
    script_location = "${local.scripts_base}/job_clean.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--TempDir"                          = "s3://${var.trusted_bucket_id}/_glue-temp/"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--extra-py-files"                   = "${local.scripts_base}/transforms.py"
    "--dt"                               = "2024-01-01"
    "--bucket_raw"                       = var.raw_bucket_id
    "--bucket_trusted"                   = var.trusted_bucket_id
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags       = var.tags
  depends_on = [aws_s3_object.job_clean, aws_s3_object.transforms]
}

resource "aws_glue_job" "agg" {
  name              = "${local.name_prefix}-job-agg"
  role_arn          = aws_iam_role.agg.arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.job_timeout_minutes

  command {
    name            = "glueetl"
    script_location = "${local.scripts_base}/job_agg.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--TempDir"                          = "s3://${var.data_product_bucket_id}/_glue-temp/"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--extra-py-files"                   = "${local.scripts_base}/transforms.py"
    "--dt"                               = "2024-01-01"
    "--bucket_trusted"                   = var.trusted_bucket_id
    "--bucket_product"                   = var.data_product_bucket_id
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags       = var.tags
  depends_on = [aws_s3_object.job_agg, aws_s3_object.transforms]
}

# ---------------------------------------------------------------------------
# Crawler over the data-product output (on-demand; schedule disabled).
# ---------------------------------------------------------------------------
resource "aws_glue_crawler" "data_product" {
  name          = "${local.name_prefix}-crawler-data-product"
  role          = aws_iam_role.crawler.arn
  database_name = var.customer_sentiment_db_name

  s3_target {
    path = "s3://${var.data_product_bucket_id}/customer_sentiment_by_age"
  }

  # delete_behavior LOG => never deletes tables (DELETE_FROM_DATABASE = false).
  schema_change_policy {
    delete_behavior = "LOG"
    # LOG prevents the crawler from mutating column definitions on a table that
    # is already managed by Terraform (avoids duplicate dt partition/column).
    update_behavior = "LOG"
  }

  tags = var.tags

  depends_on = [
    aws_lakeformation_permissions.crawler_location,
    aws_lakeformation_permissions.crawler_database,
    aws_lakeformation_permissions.crawler_tables,
  ]
}
