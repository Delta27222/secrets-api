# ============================================================================
# Terraform Configuration - Rotation + Reencryptación Lambda
# ============================================================================

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Descomentar si quieres usar remote state (S3 + DynamoDB)
  # backend "s3" {
  #   bucket         = "tek-secrets-terraform-state"
  #   key            = "deployment/lambda/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ============================================================================
# 1. SQS Queue (Main + DLQ)
# ============================================================================

resource "aws_sqs_queue" "rotation_dlq" {
  name                      = "${var.project_name}-rotation-dlq"
  message_retention_seconds = var.sqs_message_retention

  tags = {
    Name = "${var.project_name}-rotation-dlq"
  }
}

resource "aws_sqs_queue" "rotation_queue" {
  name                       = "${var.project_name}-rotation-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = var.sqs_message_retention

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.rotation_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = {
    Name = "${var.project_name}-rotation-queue"
  }
}

# ============================================================================
# 2. IAM Role para Lambda Maestro
# ============================================================================

resource "aws_iam_role" "lambda_master_role" {
  name = "${var.project_name}-lambda-master-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-lambda-master-role"
  }
}

# Policy: CloudWatch Logs
resource "aws_iam_role_policy" "lambda_master_logs" {
  name = "${var.project_name}-lambda-master-logs"
  role = aws_iam_role.lambda_master_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/*"
      }
    ]
  })
}

# Policy: SQS SendMessage
resource "aws_iam_role_policy" "lambda_master_sqs" {
  name = "${var.project_name}-lambda-master-sqs"
  role = aws_iam_role.lambda_master_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage"
        ]
        Resource = aws_sqs_queue.rotation_queue.arn
      }
    ]
  })
}

# ============================================================================
# 3. IAM Role para Lambda Worker
# ============================================================================

resource "aws_iam_role" "lambda_worker_role" {
  name = "${var.project_name}-lambda-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-lambda-worker-role"
  }
}

# Policy: CloudWatch Logs
resource "aws_iam_role_policy" "lambda_worker_logs" {
  name = "${var.project_name}-lambda-worker-logs"
  role = aws_iam_role.lambda_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/*"
      }
    ]
  })
}

# Policy: SQS ReceiveMessage + DeleteMessage
resource "aws_iam_role_policy" "lambda_worker_sqs" {
  name = "${var.project_name}-lambda-worker-sqs"
  role = aws_iam_role.lambda_worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.rotation_queue.arn,
          aws_sqs_queue.rotation_dlq.arn
        ]
      }
    ]
  })
}

# ============================================================================
# 4. Lambda Function - Maestro
# ============================================================================

resource "aws_lambda_function" "rotation_master" {
  filename         = "lambda_master.zip"
  function_name    = "${var.project_name}-rotation-master"
  role             = aws_iam_role.lambda_master_role.arn
  handler          = "rotation_master.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_master_timeout
  memory_size      = var.lambda_master_memory
  source_code_hash = filebase64sha256("lambda_master.zip")

  environment {
    variables = {
      MONGODB_URL            = var.mongodb_url
      MONGO_DB               = var.mongo_db
      SQS_QUEUE_URL          = aws_sqs_queue.rotation_queue.id
      ROTATION_INTERVAL_DAYS = var.rotation_interval_days
      ENVIRONMENT            = var.environment
    }
  }

  tags = {
    Name = "${var.project_name}-rotation-master"
  }

  depends_on = [
    aws_iam_role_policy.lambda_master_logs,
    aws_iam_role_policy.lambda_master_sqs
  ]
}

# ============================================================================
# 5. Lambda Function - Worker
# ============================================================================

resource "aws_lambda_function" "rotation_worker" {
  filename         = "lambda_worker.zip"
  function_name    = "${var.project_name}-rotation-worker"
  role             = aws_iam_role.lambda_worker_role.arn
  handler          = "rotation_worker.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_worker_timeout
  memory_size      = var.lambda_worker_memory
  source_code_hash = filebase64sha256("lambda_worker.zip")

  environment {
    variables = {
      API_BASE_URL       = var.api_base_url
      ROTATION_API_TOKEN = var.rotation_api_token
      ENVIRONMENT        = var.environment
    }
  }

  tags = {
    Name = "${var.project_name}-rotation-worker"
  }

  depends_on = [
    aws_iam_role_policy.lambda_worker_logs,
    aws_iam_role_policy.lambda_worker_sqs
  ]
}

# ============================================================================
# 6. SQS Event Source Mapping (SQS → Lambda Worker)
# ============================================================================

resource "aws_lambda_event_source_mapping" "sqs_to_lambda" {
  event_source_arn  = aws_sqs_queue.rotation_queue.arn
  function_name     = aws_lambda_function.rotation_worker.arn
  batch_size        = var.sqs_batch_size
  enabled           = true

  # Configurar visibilidad de errores en SQS
  function_response_types = ["ReportBatchItemFailures"]
}

# ============================================================================
# 7. EventBridge Rule (Cron Scheduler)
# ============================================================================

resource "aws_cloudwatch_event_rule" "rotation_schedule" {
  name                = "${var.project_name}-rotation-schedule"
  description         = var.rotation_schedule_description
  schedule_expression = var.rotation_schedule
  state               = "ENABLED"

  tags = {
    Name = "${var.project_name}-rotation-schedule"
  }
}

resource "aws_cloudwatch_event_target" "rotation_lambda_master" {
  rule      = aws_cloudwatch_event_rule.rotation_schedule.name
  target_id = "RotationMasterLambda"
  arn       = aws_lambda_function.rotation_master.arn

  # Input: enviar timestamp para logging
  input = jsonencode({
    source     = "eventbridge"
    triggered  = true
    timestamp  = "$${aws:EventTime}"
  })
}

# Permitir que EventBridge invoque Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rotation_master.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rotation_schedule.arn
}

# ============================================================================
# 8. CloudWatch Log Groups (explícito para better control)
# ============================================================================

resource "aws_cloudwatch_log_group" "lambda_master_logs" {
  name              = "/aws/lambda/${aws_lambda_function.rotation_master.function_name}"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-lambda-master-logs"
  }
}

resource "aws_cloudwatch_log_group" "lambda_worker_logs" {
  name              = "/aws/lambda/${aws_lambda_function.rotation_worker.function_name}"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-lambda-worker-logs"
  }
}

# ============================================================================
# 9. CloudWatch Alarms
# ============================================================================

resource "aws_cloudwatch_metric_alarm" "lambda_master_errors" {
  alarm_name          = "${var.project_name}-lambda-master-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1

  dimensions = {
    FunctionName = aws_lambda_function.rotation_master.function_name
  }

  alarm_description = "Alert when Lambda Maestro tiene errores"
  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project_name}-lambda-master-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_worker_errors" {
  alarm_name          = "${var.project_name}-lambda-worker-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1

  dimensions = {
    FunctionName = aws_lambda_function.rotation_worker.function_name
  }

  alarm_description = "Alert when Lambda Worker tiene errores"
  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project_name}-lambda-worker-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "sqs_dlq_messages" {
  alarm_name          = "${var.project_name}-sqs-dlq-messages"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = 1

  dimensions = {
    QueueName = aws_sqs_queue.rotation_dlq.name
  }

  alarm_description = "Alert when hay mensajes en DLQ (procesamiento falló)"
  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project_name}-sqs-dlq-messages"
  }
}
