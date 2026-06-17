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

output "lake_formation_databases" {
  description = "Glue databases managed by Lake Formation."
  value = {
    reviews_trusted    = module.lake_formation.reviews_trusted_database
    customer_sentiment = module.lake_formation.customer_sentiment_database
  }
}

output "customer_sentiment_table" {
  description = "Fully qualified name of the data-product table."
  value       = module.lake_formation.customer_sentiment_table
}

output "lake_formation_registered_locations" {
  description = "S3 locations registered with Lake Formation."
  value       = module.lake_formation.registered_locations
}

output "glue_jobs" {
  description = "Provisioned Glue jobs."
  value = {
    job_clean = module.glue.job_clean_name
    job_agg   = module.glue.job_agg_name
  }
}

output "glue_crawler" {
  description = "Provisioned Glue crawler."
  value       = module.glue.crawler_name
}

output "glue_script_locations" {
  description = "S3 URIs of the uploaded Glue scripts."
  value       = module.glue.script_locations
}

output "state_machine_arn" {
  description = "ARN of the sentiment pipeline Step Functions state machine."
  value       = module.step_functions.state_machine_arn
}

output "state_machine_name" {
  description = "Name of the sentiment pipeline Step Functions state machine."
  value       = module.step_functions.state_machine_name
}

output "state_machine_log_group" {
  description = "CloudWatch log group for Step Functions pipeline executions."
  value       = module.step_functions.log_group_name
}
