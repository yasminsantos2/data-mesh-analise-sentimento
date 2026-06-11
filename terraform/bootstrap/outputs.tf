output "state_bucket_name" {
  description = "S3 bucket holding Terraform remote state."
  value       = aws_s3_bucket.state.id
}

output "lock_table_name" {
  description = "DynamoDB table used for state locking."
  value       = aws_dynamodb_table.lock.name
}
