# Least-privilege IAM: one role per Lambda, scoped to exactly the resources
# each function touches. The agent role is the broadest (it executes plans)
# but is still enumerated — no wildcards on resources except where the API
# requires it (Cost Explorer, EventBridge PutEvents to the named bus).

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

locals {
  lambda_roles = toset(["agent", "discovery", "drift", "failure", "cost", "docs", "worker"])
}

resource "aws_iam_role" "lambda" {
  for_each           = local.lambda_roles
  name               = "${local.name}-${each.key}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Shared baseline: logs, metrics, state table, KMS, event bus.
data "aws_iam_policy_document" "baseline" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name}-*"]
  }
  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["ADE"]
    }
  }
  statement {
    sid     = "StateTable"
    actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [
      aws_dynamodb_table.state.arn,
      "${aws_dynamodb_table.state.arn}/index/*",
    ]
  }
  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.ade.arn]
  }
  statement {
    sid       = "EmitEvents"
    actions   = ["events:PutEvents"]
    resources = [aws_cloudwatch_event_bus.ade.arn]
  }
}

resource "aws_iam_role_policy" "baseline" {
  for_each = aws_iam_role.lambda
  name     = "baseline"
  role     = each.value.id
  policy   = data.aws_iam_policy_document.baseline.json
}

# Agent: invoke Bedrock, start state machines, publish alerts, start crawlers.
data "aws_iam_policy_document" "agent" {
  statement {
    sid       = "Bedrock"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:${var.region}::foundation-model/anthropic.*"]
  }
  statement {
    sid     = "StartPipelines"
    actions = ["states:StartExecution"]
    resources = [
      local.etl_sfn_arn,
      local.retrain_sfn_arn,
    ]
  }
  statement {
    sid       = "Alerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn, aws_sns_topic.approvals.arn]
  }
  statement {
    sid       = "Crawlers"
    actions   = ["glue:StartCrawler", "glue:GetCrawler"]
    resources = ["arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:crawler/${local.name}-*"]
  }
}

resource "aws_iam_role_policy" "agent" {
  name   = "agent"
  role   = aws_iam_role.lambda["agent"].id
  policy = data.aws_iam_policy_document.agent.json
}

# Discovery: read-only catalog/source enumeration.
data "aws_iam_policy_document" "discovery" {
  statement {
    sid     = "ListDataLake"
    actions = ["s3:ListBucket", "s3:GetObject"]
    resources = [
      aws_s3_bucket.ade["data-lake"].arn,
      "${aws_s3_bucket.ade["data-lake"].arn}/*",
    ]
  }
  statement {
    sid       = "GlueRead"
    actions   = ["glue:GetDatabases", "glue:GetTables"]
    resources = ["*"]
  }
  statement {
    sid       = "RdsRead"
    actions   = ["rds:DescribeDBInstances", "rds:ListTagsForResource"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "discovery" {
  name   = "discovery"
  role   = aws_iam_role.lambda["discovery"].id
  policy = data.aws_iam_policy_document.discovery.json
}

# Drift: read data lake samples.
data "aws_iam_policy_document" "drift" {
  statement {
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.ade["data-lake"].arn,
      "${aws_s3_bucket.ade["data-lake"].arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "drift" {
  name   = "drift"
  role   = aws_iam_role.lambda["drift"].id
  policy = data.aws_iam_policy_document.drift.json
}

# Cost: Cost Explorer is account-wide by API design.
data "aws_iam_policy_document" "cost" {
  statement {
    actions   = ["ce:GetCostAndUsage"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "cost" {
  name   = "cost"
  role   = aws_iam_role.lambda["cost"].id
  policy = data.aws_iam_policy_document.cost.json
}

# Docs: write handbook to docs bucket.
data "aws_iam_policy_document" "docs" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.ade["docs"].arn}/*"]
  }
}

resource "aws_iam_role_policy" "docs" {
  name   = "docs"
  role   = aws_iam_role.lambda["docs"].id
  policy = data.aws_iam_policy_document.docs.json
}

# Worker (ETL steps inside the state machine): read/write data lake.
data "aws_iam_policy_document" "worker" {
  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
    resources = [
      aws_s3_bucket.ade["data-lake"].arn,
      "${aws_s3_bucket.ade["data-lake"].arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "worker"
  role   = aws_iam_role.lambda["worker"].id
  policy = data.aws_iam_policy_document.worker.json
}

# Step Functions execution role: invoke the worker Lambda + SageMaker.
resource "aws_iam_role" "sfn" {
  name = "${local.name}-sfn-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  name = "sfn"
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeWorker"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = [aws_lambda_function.ade["worker"].arn, aws_lambda_function.ade["agent"].arn]
      },
      {
        Sid    = "SageMaker"
        Effect = "Allow"
        Action = [
          "sagemaker:CreateTrainingJob",
          "sagemaker:DescribeTrainingJob",
          "sagemaker:StopTrainingJob",
          "sagemaker:AddTags",
        ]
        Resource = "arn:aws:sagemaker:${var.region}:${data.aws_caller_identity.current.account_id}:training-job/ade-*"
      },
      {
        Sid      = "PassSagemakerRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.sagemaker.arn
      },
      {
        Sid      = "EventsForSfnIntegration"
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "arn:aws:events:${var.region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctions*"
      },
    ]
  })
}

# SageMaker training role.
resource "aws_iam_role" "sagemaker" {
  name = "${local.name}-sagemaker-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "sagemaker.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "sagemaker" {
  name = "sagemaker"
  role = aws_iam_role.sagemaker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.ade["data-lake"].arn,
          "${aws_s3_bucket.ade["data-lake"].arn}/*",
          aws_s3_bucket.ade["artifacts"].arn,
          "${aws_s3_bucket.ade["artifacts"].arn}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/sagemaker/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.ade.arn
      },
    ]
  })
}
