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
