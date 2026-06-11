variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used as a prefix for all resource names."
  type        = string
  default     = "data-mesh-sentimento"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}

variable "glacier_transition_days" {
  description = "Days after which S3 objects transition to Glacier."
  type        = number
  default     = 90
}

variable "athena_results_prefix" {
  description = "Prefix inside the data-product bucket for Athena query results."
  type        = string
  default     = "athena-results"
}

variable "force_destroy" {
  description = "Allow destroying non-empty buckets. Useful only in dev."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}
