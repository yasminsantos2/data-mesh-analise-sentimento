variable "project_name" {
  description = "Project name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "bucket_suffix" {
  description = "Suffix for global S3 bucket uniqueness (e.g. AWS account ID)."
  type        = string
  default     = ""
}

variable "athena_role_name" {
  description = "Name of the Marketing Athena IAM role (from the iam module)."
  type        = string
}

variable "customer_sentiment_database" {
  description = "Glue database queried by the analytical views."
  type        = string
  default     = "customer_sentiment"
}

variable "workgroup_name" {
  description = "Dedicated Athena workgroup for the Marketing team."
  type        = string
  default     = "marketing_wg"
}

variable "results_prefix" {
  description = "Prefix inside the results bucket for marketing queries."
  type        = string
  default     = "marketing"
}

variable "bytes_scanned_cutoff_per_query" {
  description = "Maximum bytes scanned per query (1 GB default)."
  type        = number
  default     = 1073741824
}

variable "force_destroy" {
  description = "Allow destroying a non-empty results bucket (dev only)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to created resources."
  type        = map(string)
  default     = {}
}
