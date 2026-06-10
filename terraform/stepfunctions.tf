# ETL pipeline state machine. The default definition mirrors what
# ade.etl.pipeline_builder.compile_to_asl generates; per-dataset pipelines
# pass their spec in the execution input and the worker dispatches on it.

resource "aws_sfn_state_machine" "etl" {
  name     = "${local.name}-etl"
  role_arn = aws_iam_role.sfn.arn

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  definition = jsonencode({
    Comment = "ADE generic ETL pipeline: extract -> validate -> transform -> quality gate -> load"
    StartAt = "Extract"
    States = {
      Extract = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "extract", "input.$" = "$" }
        ResultPath = "$.extract_result"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed", "Lambda.ServiceException"]
          IntervalSeconds = 10
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Quarantine" }]
        Next  = "Validate"
      }
      Validate = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "validate", "input.$" = "$" }
        ResultPath = "$.validate_result"
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Quarantine" }]
        Next       = "Transform"
      }
      Transform = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "transform", "input.$" = "$" }
        ResultPath = "$.transform_result"
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Quarantine" }]
        Next       = "QualityGate"
      }
      QualityGate = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "quality_gate", "input.$" = "$" }
        ResultPath = "$.quality_result"
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Quarantine" }]
        Next       = "QualityChoice"
      }
      QualityChoice = {
        Type    = "Choice"
        Choices = [{ Variable = "$.quality_result.passed", BooleanEquals = true, Next = "Load" }]
        Default = "Quarantine"
      }
      Load = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "load", "input.$" = "$" }
        End        = true
      }
      Quarantine = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "quarantine", "input.$" = "$" }
        Next       = "FailPipeline"
      }
      FailPipeline = {
        Type  = "Fail"
        Error = "PipelineFailed"
        Cause = "Quality gate failed or a step errored; records quarantined."
      }
    }
  })
}

# Retraining state machine: train (SageMaker, sync) -> evaluate -> gate.
# Promotion itself is NOT here — the agent requests it and a human approves.

resource "aws_sfn_state_machine" "retrain" {
  name     = "${local.name}-retrain"
  role_arn = aws_iam_role.sfn.arn

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  definition = jsonencode({
    Comment = "ADE model retraining: train -> evaluate -> promotion gate"
    StartAt = "Train"
    States = {
      Train = {
        Type     = "Task"
        Resource = "arn:aws:states:::sagemaker:createTrainingJob.sync"
        Parameters = {
          "TrainingJobName.$" = "$.job_name"
          AlgorithmSpecification = {
            "TrainingImage.$" = "$.image_uri"
            TrainingInputMode = "File"
          }
          RoleArn = aws_iam_role.sagemaker.arn
          InputDataConfig = [{
            ChannelName = "train"
            DataSource = {
              S3DataSource = {
                S3DataType                 = "S3Prefix"
                "S3Uri.$"                  = "$.train_s3_uri"
                S3DataDistributionType     = "FullyReplicated"
              }
            }
          }]
          OutputDataConfig = { "S3OutputPath.$" = "$.output_s3_uri" }
          ResourceConfig = {
            "InstanceType.$" = "$.instance_type"
            InstanceCount    = 1
            VolumeSizeInGB   = 50
          }
          StoppingCondition = { MaxRuntimeInSeconds = 7200 }
        }
        ResultPath = "$.training_result"
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "NotifyFailure" }]
        Next       = "Evaluate"
      }
      Evaluate = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["worker"].arn
        Parameters = { step = "evaluate_model", "input.$" = "$" }
        ResultPath = "$.evaluation"
        Next       = "PromotionGate"
      }
      PromotionGate = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["agent"].arn
        Parameters = {
          detail = {
            type           = "model_evaluated"
            "id.$"         = "$.job_name"
            "evaluation.$" = "$.evaluation"
          }
        }
        End = true
      }
      NotifyFailure = {
        Type       = "Task"
        Resource   = aws_lambda_function.ade["agent"].arn
        Parameters = {
          detail = {
            type           = "pipeline_failed"
            "id.$"         = "$.job_name"
            "incident_id.$" = "$.job_name"
            "error_text.$" = "States.JsonToString($.error)"
          }
        }
        Next = "FailRetrain"
      }
      FailRetrain = {
        Type  = "Fail"
        Error = "RetrainFailed"
      }
    }
  })
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${local.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.ade.arn
}
