terraform {
  # Remote state stored in S3 with a DynamoDB table for state locking.
  #
  # The backend block cannot use variables, so these values are hard-coded.
  # The state bucket and the lock table must exist BEFORE running
  # `terraform init` (bootstrap them once, manually or with a separate stack).
  backend "s3" {
    bucket         = "data-mesh-sentimento-tfstate-082846230365"
    key            = "environments/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "data-mesh-sentimento-tflock"
    encrypt        = true
  }
}
