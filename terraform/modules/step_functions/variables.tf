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
  description = "Raw S3 bucket name."
  type        = string
}

variable "raw_bucket_arn" {
  description = "Raw S3 bucket ARN."
  type        = string
}

variable "trusted_bucket_id" {
  description = "Trusted S3 bucket name."
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

variable "athena_results_prefix" {
  description = "Prefix inside the data-product bucket for Athena query results."
  type        = string
  default     = "athena-results"
}

variable "definition_source_path" {
  description = "Path to the versioned state_machine.asl.json definition (Terraform template)."
  type        = string
}

variable "raw_database_name" {
  description = "Glue database used by Athena to count raw partition rows."
  type        = string
  default     = "reviews_raw"
}

variable "raw_table_name" {
  description = "Glue table name for raw CSV reviews."
  type        = string
  default     = "reviews"
}

variable "tags" {
  description = "Tags applied to created resources."
  type        = map(string)
  default     = {}
}
