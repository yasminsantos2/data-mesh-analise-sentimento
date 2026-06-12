output "reviews_trusted_database" {
  description = "Name of the trusted-layer Glue database."
  value       = aws_glue_catalog_database.reviews_trusted.name
}

output "customer_sentiment_database" {
  description = "Name of the data-product Glue database."
  value       = aws_glue_catalog_database.customer_sentiment.name
}

output "customer_sentiment_table" {
  description = "Fully qualified name of the data-product table."
  value       = "${aws_glue_catalog_database.customer_sentiment.name}.${aws_glue_catalog_table.customer_sentiment_by_age.name}"
}

output "registered_locations" {
  description = "S3 ARNs registered as Lake Formation data lake locations."
  value = [
    aws_lakeformation_resource.trusted.arn,
    aws_lakeformation_resource.data_product.arn,
  ]
}

output "lake_formation_admins" {
  description = "Principals registered as Lake Formation admins."
  value       = local.admin_arns
}
