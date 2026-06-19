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

output "default_pipeline_input" {
  description = "Example execution input (replace dt with YYYY-MM-DD)."
  value       = local.default_input
}
