terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Remote state — fill in and uncomment for team use.
  # backend "s3" {
  #   bucket         = "<state-bucket>"
  #   key            = "ade/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "<lock-table>"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
