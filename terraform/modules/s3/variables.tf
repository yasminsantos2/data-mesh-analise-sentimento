variable "project_name" {
  description = "Project name used as a prefix for bucket names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. dev, stg, prod)."
  type        = string
}

variable "bucket_layers" {
  description = "Logical data mesh layers. One S3 bucket is created per layer."
  type        = list(string)
  default     = ["raw", "trusted", "data-product"]
}

variable "glacier_transition_days" {
  description = "Number of days after which current object versions transition to Glacier."
  type        = number
  default     = 90
}

variable "force_destroy" {
  description = "Allow Terraform to destroy non-empty buckets. Keep false outside throwaway environments."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every bucket."
  type        = map(string)
  default     = {}
}
