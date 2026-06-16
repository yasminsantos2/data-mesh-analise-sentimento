terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

module "s3" {
  source = "../../modules/s3"

  project_name            = var.project_name
  environment             = var.environment
  bucket_suffix           = data.aws_caller_identity.current.account_id
  glacier_transition_days = var.glacier_transition_days
  force_destroy           = var.force_destroy
  tags                    = local.common_tags
}

module "iam" {
  source = "../../modules/iam"

  project_name            = var.project_name
  environment             = var.environment
  raw_bucket_arn          = module.s3.raw_bucket_arn
  trusted_bucket_arn      = module.s3.trusted_bucket_arn
  data_product_bucket_arn = module.s3.data_product_bucket_arn
  athena_results_prefix   = var.athena_results_prefix
  tags                    = local.common_tags
}

module "lake_formation" {
  source = "../../modules/lake_formation"

  glue_role_arn           = module.iam.glue_role_arn
  athena_role_arn         = module.iam.athena_role_arn
  trusted_bucket_arn      = module.s3.trusted_bucket_arn
  data_product_bucket_arn = module.s3.data_product_bucket_arn
  tags                    = local.common_tags
}

module "glue" {
  source = "../../modules/glue"

  project_name               = var.project_name
  environment                = var.environment
  glue_role_arn              = module.iam.glue_role_arn
  raw_bucket_id              = module.s3.bucket_ids["raw"]
  trusted_bucket_id          = module.s3.bucket_ids["trusted"]
  data_product_bucket_id     = module.s3.bucket_ids["data-product"]
  trusted_bucket_arn         = module.s3.trusted_bucket_arn
  data_product_bucket_arn    = module.s3.data_product_bucket_arn
  customer_sentiment_db_name = module.lake_formation.customer_sentiment_database
  scripts_source_dir         = "${path.module}/../../../glue_jobs"
  tags                       = local.common_tags

  # The crawler's Lake Formation grants (DATA_LOCATION_ACCESS / database) require
  # the data-product location to be registered first by the lake_formation module.
  depends_on = [module.lake_formation]
}
