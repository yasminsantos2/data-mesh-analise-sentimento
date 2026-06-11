output "bucket_ids" {
  description = "Map of layer => bucket name."
  value       = { for layer, b in aws_s3_bucket.this : layer => b.id }
}

output "bucket_arns" {
  description = "Map of layer => bucket ARN."
  value       = { for layer, b in aws_s3_bucket.this : layer => b.arn }
}

output "raw_bucket_arn" {
  description = "ARN of the raw layer bucket."
  value       = aws_s3_bucket.this["raw"].arn
}

output "trusted_bucket_arn" {
  description = "ARN of the trusted layer bucket."
  value       = aws_s3_bucket.this["trusted"].arn
}

output "data_product_bucket_arn" {
  description = "ARN of the data-product layer bucket."
  value       = aws_s3_bucket.this["data-product"].arn
}

output "data_product_bucket_id" {
  description = "Name of the data-product layer bucket."
  value       = aws_s3_bucket.this["data-product"].id
}
