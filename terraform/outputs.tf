output "data_lake_bucket" {
  value = aws_s3_bucket.ade["data-lake"].bucket
}

output "docs_bucket" {
  value = aws_s3_bucket.ade["docs"].bucket
}

output "state_table" {
  value = aws_dynamodb_table.state.name
}

output "event_bus" {
  value = aws_cloudwatch_event_bus.ade.name
}

output "etl_state_machine_arn" {
  value = aws_sfn_state_machine.etl.arn
}

output "retrain_state_machine_arn" {
  value = aws_sfn_state_machine.retrain.arn
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${local.name}"
}

output "agent_lambda" {
  value = aws_lambda_function.ade["agent"].function_name
}
