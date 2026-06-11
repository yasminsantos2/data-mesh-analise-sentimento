variable "project_name" {
  description = "Project name used as a prefix for role names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. dev, stg, prod)."
  type        = string
}

variable "raw_bucket_arn" {
  description = "ARN of the raw layer bucket (Glue reads from here)."
  type        = string
}

variable "trusted_bucket_arn" {
  description = "ARN of the trusted layer bucket (Glue writes here)."
  type        = string
}

variable "data_product_bucket_arn" {
  description = "ARN of the data-product layer bucket (Athena reads here)."
  type        = string
}

variable "athena_results_prefix" {
  description = "Key prefix inside the data-product bucket where Athena writes query results."
  type        = string
  default     = "athena-results"
}

variable "tags" {
  description = "Tags applied to every IAM role."
  type        = map(string)
  default     = {}
}
