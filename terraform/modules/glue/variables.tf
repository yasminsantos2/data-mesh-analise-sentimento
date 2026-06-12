variable "project_name" {
  description = "Project name used as a prefix for resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "glue_role_arn" {
  description = "ARN of the existing glue_role (reads raw, writes trusted). Used by job_clean."
  type        = string
}

variable "raw_bucket_id" {
  description = "Name of the raw bucket."
  type        = string
}

variable "trusted_bucket_id" {
  description = "Name of the trusted bucket."
  type        = string
}

variable "data_product_bucket_id" {
  description = "Name of the data-product bucket."
  type        = string
}

variable "trusted_bucket_arn" {
  description = "ARN of the trusted bucket."
  type        = string
}

variable "data_product_bucket_arn" {
  description = "ARN of the data-product bucket."
  type        = string
}

variable "customer_sentiment_db_name" {
  description = "Glue database the crawler writes to."
  type        = string
  default     = "customer_sentiment"
}

variable "scripts_prefix" {
  description = "Key prefix (in the trusted bucket) where Glue scripts are uploaded."
  type        = string
  default     = "assets/glue"
}

variable "glue_version" {
  description = "AWS Glue version."
  type        = string
  default     = "4.0"
}

variable "worker_type" {
  description = "Glue worker type."
  type        = string
  default     = "G.1X"
}

variable "number_of_workers" {
  description = "Number of Glue workers per job."
  type        = number
  default     = 2
}

variable "job_timeout_minutes" {
  description = "Job timeout in minutes."
  type        = number
  default     = 30
}

variable "scripts_source_dir" {
  description = "Local directory containing the PySpark scripts."
  type        = string
}

variable "tags" {
  description = "Tags applied to resources that support tagging."
  type        = map(string)
  default     = {}
}
