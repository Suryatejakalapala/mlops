# One deployment package, multiple functions — each maps to a handler in
# ade/lambdas/handlers.py. CI builds dist/ade-lambda.zip; for a first
# `terraform apply` without CI, `make package` produces the same artifact.

locals {
  functions = {
    agent     = { handler = "ade.lambdas.handlers.agent_handler", timeout = 300, memory = 512 }
    discovery = { handler = "ade.lambdas.handlers.discovery_handler", timeout = 300, memory = 512 }
    drift     = { handler = "ade.lambdas.handlers.drift_handler", timeout = 120, memory = 512 }
    failure   = { handler = "ade.lambdas.handlers.pipeline_failure_handler", timeout = 60, memory = 256 }
    cost      = { handler = "ade.lambdas.handlers.cost_handler", timeout = 120, memory = 256 }
    docs      = { handler = "ade.lambdas.handlers.docs_handler", timeout = 120, memory = 256 }
    # Worker executes ETL steps inside the state machine; reuses the same
    # package (step dispatch on the "step" field of its input).
    worker = { handler = "ade.lambdas.handlers.agent_handler", timeout = 600, memory = 1024 }
  }

  # ARNs constructed by convention to avoid a lambda <-> state-machine
  # dependency cycle (the state machines invoke the worker lambda).
  etl_sfn_arn     = "arn:aws:states:${var.region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.name}-etl"
  retrain_sfn_arn = "arn:aws:states:${var.region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.name}-retrain"

  common_env = {
    ADE_PROJECT             = var.project
    ADE_ENV                 = var.environment
    ADE_DATA_LAKE_BUCKET    = aws_s3_bucket.ade["data-lake"].bucket
    ADE_ARTIFACTS_BUCKET    = aws_s3_bucket.ade["artifacts"].bucket
    ADE_DOCS_BUCKET         = aws_s3_bucket.ade["docs"].bucket
    ADE_STATE_TABLE         = aws_dynamodb_table.state.name
    ADE_ALERTS_TOPIC_ARN    = aws_sns_topic.alerts.arn
    ADE_APPROVALS_TOPIC_ARN = aws_sns_topic.approvals.arn
    ADE_EVENT_BUS           = aws_cloudwatch_event_bus.ade.name
    ADE_ETL_SFN_ARN         = local.etl_sfn_arn
    ADE_RETRAIN_SFN_ARN     = local.retrain_sfn_arn
    ADE_PLANNER_MODEL       = var.planner_model
    ADE_DRY_RUN             = var.dry_run ? "true" : "false"
  }
}

resource "aws_lambda_function" "ade" {
  for_each = local.functions

  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  handler          = each.value.handler
  runtime          = "python3.12"
  timeout          = each.value.timeout
  memory_size      = each.value.memory
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = local.common_env
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.ade.arn
}
