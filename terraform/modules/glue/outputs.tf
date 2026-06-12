output "job_clean_name" {
  description = "Name of the cleaning Glue job."
  value       = aws_glue_job.clean.name
}

output "job_agg_name" {
  description = "Name of the aggregation Glue job."
  value       = aws_glue_job.agg.name
}

output "crawler_name" {
  description = "Name of the data-product crawler."
  value       = aws_glue_crawler.data_product.name
}

output "agg_role_arn" {
  description = "ARN of the job_agg role."
  value       = aws_iam_role.agg.arn
}

output "crawler_role_arn" {
  description = "ARN of the crawler role."
  value       = aws_iam_role.crawler.arn
}

output "script_locations" {
  description = "S3 URIs of the uploaded Glue scripts."
  value = {
    job_clean  = "${local.scripts_base}/job_clean.py"
    job_agg    = "${local.scripts_base}/job_agg.py"
    transforms = "${local.scripts_base}/transforms.py"
  }
}
