# Monitoring stack: dashboard + alarms wired to the alerts topic.

resource "aws_cloudwatch_dashboard" "ade" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "Agent decisions"
          region = var.region
          stat   = "Sum"
          period = 300
          metrics = [
            ["ADE", "PlansAccepted", "Environment", var.environment],
            ["ADE", "PlansRejected", "Environment", var.environment],
            ["ADE", "PlannerErrors", "Environment", var.environment],
            ["ADE", "EscalationsTriggered", "Environment", var.environment],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Action outcomes"
          region = var.region
          stat   = "Sum"
          period = 300
          metrics = [
            ["ADE", "Action.executed", "Environment", var.environment],
            ["ADE", "Action.dry_run", "Environment", var.environment],
            ["ADE", "Action.approval_requested", "Environment", var.environment],
            ["ADE", "Action.failed", "Environment", var.environment],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Lambda errors"
          region = var.region
          stat   = "Sum"
          period = 300
          metrics = [
            for fn in keys(local.functions) :
            ["AWS/Lambda", "Errors", "FunctionName", "${local.name}-${fn}"]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "ETL pipeline executions"
          region = var.region
          stat   = "Sum"
          period = 3600
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", local.etl_sfn_arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", local.etl_sfn_arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", local.retrain_sfn_arn],
          ]
        }
      },
    ]
  })
}

# Agent loop is broken (planner failing repeatedly).
resource "aws_cloudwatch_metric_alarm" "planner_errors" {
  alarm_name          = "${local.name}-planner-errors"
  namespace           = "ADE"
  metric_name         = "PlannerErrors"
  dimensions          = { Environment = var.environment }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  alarm_description   = "ADE planner (Bedrock) failing — agent cannot make decisions."
}

# Plans being rejected means the model is proposing disallowed actions.
resource "aws_cloudwatch_metric_alarm" "plans_rejected" {
  alarm_name          = "${local.name}-plans-rejected"
  namespace           = "ADE"
  metric_name         = "PlansRejected"
  dimensions          = { Environment = var.environment }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  alarm_description   = "ADE plan validation rejecting many plans — review planner prompt."
}

resource "aws_cloudwatch_metric_alarm" "agent_lambda_errors" {
  alarm_name          = "${local.name}-agent-lambda-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.ade["agent"].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "etl_failures" {
  alarm_name          = "${local.name}-etl-failures"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = local.etl_sfn_arn }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  alarm_description   = "Multiple ETL failures in an hour — self-healing may be looping."
}
