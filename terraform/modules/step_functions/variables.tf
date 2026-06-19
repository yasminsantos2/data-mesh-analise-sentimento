variable "project_name" {
  description = "Project name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "sfn_role_arn" {
  description = "ARN of the Step Functions execution role (from the iam module)."
  type        = string
}

variable "sfn_role_name" {
  description = "Name of the Step Functions execution role."
  type        = string
}

variable "job_clean_name" {
  description = "Glue job_clean name."
  type        = string
}

variable "job_agg_name" {
  description = "Glue job_agg name."
  type        = string
}

variable "crawler_name" {
  description = "Glue crawler name."
  type        = string
}

variable "raw_bucket_id" {
  description = "Raw S3 bucket name (used in the default pipeline input)."
  type        = string
}

variable "trusted_bucket_id" {
  description = "Trusted S3 bucket name (used in the default pipeline input)."
  type        = string
}

variable "data_product_bucket_id" {
  description = "Data-product S3 bucket name."
  type        = string
}

variable "data_product_bucket_arn" {
  description = "Data-product S3 bucket ARN."
  type        = string
}

variable "customer_sentiment_database" {
  description = "Glue database validated by Athena at the end of the pipeline."
  type        = string
  default     = "customer_sentiment"
}

variable "customer_sentiment_table" {
  description = "Glue table validated by Athena at the end of the pipeline."
  type        = string
  default     = "customer_sentiment_by_age"
}

variable "athena_results_prefix" {
  description = "Prefix inside the data-product bucket for Athena query results."
  type        = string
  default     = "athena-results"
}

variable "tags" {
  description = "Tags applied to created resources."
  type        = map(string)
  default     = {}
}
