variable "project" {
  description = "Project name prefix for all resources."
  type        = string
  default     = "ade"
}

variable "environment" {
  description = "Deployment environment (dev/staging/prod)."
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "alert_email" {
  description = "Email subscribed to alert and approval topics."
  type        = string
}

variable "planner_model" {
  description = "Claude model id on Bedrock used by the agent planner."
  type        = string
  default     = "anthropic.claude-opus-4-8"
}

variable "dry_run" {
  description = "When true the agent logs intended actions without executing them."
  type        = bool
  default     = true
}

variable "monthly_budget_usd" {
  description = "AWS Budgets monthly cap; alerts at 80% and 100%."
  type        = number
  default     = 500
}

variable "lambda_package_path" {
  description = "Path to the built Lambda deployment zip (created by CI)."
  type        = string
  default     = "../dist/ade-lambda.zip"
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}
