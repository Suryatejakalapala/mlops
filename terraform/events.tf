# Event wiring. ADE has its own bus for agent events; schedules live on the
# default bus. Every agent-relevant event lands on the agent Lambda.

resource "aws_cloudwatch_event_bus" "ade" {
  name = local.name
}

# --- agent events (custom bus) ---------------------------------------------

resource "aws_cloudwatch_event_rule" "agent_events" {
  name           = "${local.name}-agent-events"
  event_bus_name = aws_cloudwatch_event_bus.ade.name
  event_pattern = jsonencode({
    source = ["ade.discovery", "ade.drift", "ade.recovery", "ade.cost"]
    detail-type = [
      "source_discovered", "schema_drift", "data_drift",
      "pipeline_failed", "cost_anomaly",
    ]
  })
}

resource "aws_cloudwatch_event_target" "agent_events" {
  rule           = aws_cloudwatch_event_rule.agent_events.name
  event_bus_name = aws_cloudwatch_event_bus.ade.name
  arn            = aws_lambda_function.ade["agent"].arn
}

resource "aws_lambda_permission" "agent_events" {
  statement_id  = "AllowEventBridgeAgent"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ade["agent"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.agent_events.arn
}

# --- Step Functions failures (default bus) ----------------------------------

resource "aws_cloudwatch_event_rule" "sfn_failures" {
  name = "${local.name}-sfn-failures"
  event_pattern = jsonencode({
    source      = ["aws.states"]
    detail-type = ["Step Functions Execution Status Change"]
    detail = {
      status          = ["FAILED", "TIMED_OUT", "ABORTED"]
      stateMachineArn = [local.etl_sfn_arn, local.retrain_sfn_arn]
    }
  })
}

resource "aws_cloudwatch_event_target" "sfn_failures" {
  rule = aws_cloudwatch_event_rule.sfn_failures.name
  arn  = aws_lambda_function.ade["failure"].arn
}

resource "aws_lambda_permission" "sfn_failures" {
  statement_id  = "AllowEventBridgeFailure"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ade["failure"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sfn_failures.arn
}

# --- schedules ---------------------------------------------------------------

locals {
  schedules = {
    discovery = { function = "discovery", expression = "rate(6 hours)" }
    cost      = { function = "cost", expression = "cron(0 6 * * ? *)" } # daily 06:00 UTC
    docs      = { function = "docs", expression = "cron(0 7 * * ? *)" }
  }
}

resource "aws_cloudwatch_event_rule" "schedule" {
  for_each            = local.schedules
  name                = "${local.name}-${each.key}-schedule"
  schedule_expression = each.value.expression
}

resource "aws_cloudwatch_event_target" "schedule" {
  for_each = local.schedules
  rule     = aws_cloudwatch_event_rule.schedule[each.key].name
  arn      = aws_lambda_function.ade[each.value.function].arn
}

resource "aws_lambda_permission" "schedule" {
  for_each      = local.schedules
  statement_id  = "AllowSchedule${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ade[each.value.function].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule[each.key].arn
}

# --- SNS ---------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.ade.id
}

resource "aws_sns_topic" "approvals" {
  name              = "${local.name}-approvals"
  kms_master_key_id = aws_kms_key.ade.id
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_subscription" "approvals_email" {
  topic_arn = aws_sns_topic.approvals.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
