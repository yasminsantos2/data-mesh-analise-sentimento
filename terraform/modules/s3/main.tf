locals {
  # Bucket names must be globally unique across ALL AWS accounts. An optional
  # suffix (typically the AWS account ID) is appended so the same project can
  # be deployed to multiple accounts without name collisions.
  # e.g. "data-mesh-sentimento-dev-raw-082846230365".
  name_suffix = var.bucket_suffix != "" ? "-${var.bucket_suffix}" : ""
  bucket_names = {
    for layer in var.bucket_layers :
    layer => "${var.project_name}-${var.environment}-${layer}${local.name_suffix}"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.bucket_names

  bucket        = each.value
  force_destroy = var.force_destroy

  tags = merge(var.tags, {
    Name  = each.value
    Layer = each.key
  })
}

# Versioning keeps a full history of every object, protecting against
# accidental overwrites/deletes in the data lake.
resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Block every form of public access on all buckets.
resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Server-side encryption with S3-managed keys (SSE-S3 / AES256).
resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Transition current object versions to Glacier after the configured period
# to reduce long-term storage costs.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  # Lifecycle depends on versioning being configured first.
  depends_on = [aws_s3_bucket_versioning.this]

  rule {
    id     = "transition-to-glacier"
    status = "Enabled"

    filter {}

    transition {
      days          = var.glacier_transition_days
      storage_class = "GLACIER"
    }

    noncurrent_version_transition {
      noncurrent_days = var.glacier_transition_days
      storage_class   = "GLACIER"
    }
  }
}
