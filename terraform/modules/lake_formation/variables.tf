variable "glue_role_arn" {
  description = "ARN of the Glue role. Set as Lake Formation admin and granted ALL on both databases."
  type        = string
}

variable "athena_role_arn" {
  description = "ARN of the Athena role. Granted SELECT on customer_sentiment; no access to reviews_trusted."
  type        = string
}

variable "trusted_bucket_arn" {
  description = "ARN of the trusted bucket, registered as a Lake Formation location."
  type        = string
}

variable "data_product_bucket_arn" {
  description = "ARN of the data-product bucket, registered as a Lake Formation location."
  type        = string
}

variable "reviews_trusted_db_name" {
  description = "Name of the trusted-layer Glue database."
  type        = string
  default     = "reviews_trusted"
}

variable "customer_sentiment_db_name" {
  description = "Name of the data-product Glue database."
  type        = string
  default     = "customer_sentiment"
}

variable "extra_admin_arns" {
  description = "Additional principal ARNs to register as Lake Formation admins (besides glue_role and the executing principal)."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to Glue databases/tables that support tagging."
  type        = map(string)
  default     = {}
}
