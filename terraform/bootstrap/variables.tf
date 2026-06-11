variable "aws_region" {
  description = "AWS region for the state backend resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name (tagging)."
  type        = string
  default     = "data-mesh-sentimento"
}

variable "state_bucket_name" {
  description = "Globally-unique name of the S3 bucket that stores Terraform state."
  type        = string
  default     = "data-mesh-sentimento-tfstate"
}

variable "lock_table_name" {
  description = "Name of the DynamoDB table used for state locking."
  type        = string
  default     = "data-mesh-sentimento-tflock"
}
