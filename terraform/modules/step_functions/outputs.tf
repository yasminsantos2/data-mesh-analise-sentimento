output "state_machine_arn" {
  description = "ARN of the sentiment pipeline state machine."
  value       = aws_sfn_state_machine.pipeline.arn
}

output "state_machine_name" {
  description = "Name of the sentiment pipeline state machine."
  value       = aws_sfn_state_machine.pipeline.name
}

output "log_group_name" {
  description = "CloudWatch log group for Step Functions executions."
  value       = aws_cloudwatch_log_group.sfn.name
}

output "raw_database_name" {
  description = "Glue database used for raw partition counts."
  value       = aws_glue_catalog_database.reviews_raw.name
}

output "raw_table_name" {
  description = "Glue table used for raw partition counts."
  value       = aws_glue_catalog_table.reviews.name
}
