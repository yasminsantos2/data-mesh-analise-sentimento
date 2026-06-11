output "bucket_arns" {
  description = "Map of data mesh layer => S3 bucket ARN."
  value       = module.s3.bucket_arns
}

output "bucket_ids" {
  description = "Map of data mesh layer => S3 bucket name."
  value       = module.s3.bucket_ids
}

output "glue_role_arn" {
  description = "ARN of the Glue ETL role."
  value       = module.iam.glue_role_arn
}

output "sfn_role_arn" {
  description = "ARN of the Step Functions role."
  value       = module.iam.sfn_role_arn
}

output "athena_role_arn" {
  description = "ARN of the Athena role."
  value       = module.iam.athena_role_arn
}
