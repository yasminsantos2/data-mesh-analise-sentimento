output "glue_role_arn" {
  description = "ARN of the Glue ETL role."
  value       = aws_iam_role.glue.arn
}

output "glue_role_name" {
  description = "Name of the Glue ETL role."
  value       = aws_iam_role.glue.name
}

output "sfn_role_arn" {
  description = "ARN of the Step Functions role."
  value       = aws_iam_role.sfn.arn
}

output "sfn_role_name" {
  description = "Name of the Step Functions role."
  value       = aws_iam_role.sfn.name
}

output "athena_role_arn" {
  description = "ARN of the Athena role."
  value       = aws_iam_role.athena.arn
}

output "athena_role_name" {
  description = "Name of the Athena role."
  value       = aws_iam_role.athena.name
}
