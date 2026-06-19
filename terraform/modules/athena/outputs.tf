output "workgroup_name" {
  description = "Marketing Athena workgroup name."
  value       = aws_athena_workgroup.marketing.name
}

output "workgroup_arn" {
  description = "Marketing Athena workgroup ARN."
  value       = "arn:aws:athena:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workgroup/${aws_athena_workgroup.marketing.name}"
}

output "results_bucket_id" {
  description = "S3 bucket for Marketing Athena results."
  value       = aws_s3_bucket.athena_results.id
}

output "results_bucket_arn" {
  description = "ARN of the Marketing Athena results bucket."
  value       = aws_s3_bucket.athena_results.arn
}

output "results_location" {
  description = "S3 URI prefix where marketing_wg writes query results."
  value       = local.results_uri
}

output "named_queries" {
  description = "Map of view name => named query ID."
  value       = { for k, q in aws_athena_named_query.views : k => q.id }
}

output "view_names" {
  description = "Analytical view (named query) names."
  value       = local.view_names
}
