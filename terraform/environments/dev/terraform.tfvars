aws_region              = "us-east-1"
project_name            = "data-mesh-sentimento"
environment             = "dev"
glacier_transition_days = 90
athena_results_prefix   = "athena-results"
force_destroy           = false

tags = {
  Owner   = "data-engineering"
  Domain  = "sentiment-analysis"
  CostCtr = "data-platform"
}
