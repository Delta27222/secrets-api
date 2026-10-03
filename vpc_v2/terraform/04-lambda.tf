# ============================================================================
# Grupo 4 — Lambdas
#
# 1. logs-consumer   : SQS logs-queue -> QuestDB (PG-wire :8812)
# 2. rotation-master : EventBridge cron -> MongoDB -> SQS rotation-queue
# 3. rotation-worker : SQS rotation-queue -> API (ALB) -> rota llaves
#
# MONGODB_URL ya no es un placeholder que haya que actualizar a mano tras el
# deploy — local.mongodb_url (04-secrets.tf) se conoce desde antes del apply
# porque IPs, usuario y password de Mongo son deterministas.
# ============================================================================

locals {
  consumer_zip        = "${path.module}/../../logs/terraform/lambda_consumer.zip"
  rotation_master_zip = "${path.module}/../../rotation/terraform/lambda_master.zip"
  rotation_worker_zip = "${path.module}/../../rotation/terraform/lambda_worker.zip"

  # El apex (var.domain_name pelado) NO llega al ALB — va por domain
  # forwarding de GoDaddy hacia app.* (ver Q9) y el cert wildcard tampoco
  # lo cubre. La API vive en el subdominio api.*.
  api_base_url = (
    var.domain_name != "" ? "https://api.${var.domain_name}" :
    local.effective_cert_arn != "" ? "https://${aws_lb.main.dns_name}" :
    "http://${aws_lb.main.dns_name}"
  )
}

resource "aws_cloudwatch_log_group" "lambda_consumer" {
  name              = "/aws/lambda/${var.project_name}-logs-consumer"
  retention_in_days = 30
  tags              = { Name = "${var.project_name}-lambda-consumer-logs" }
}

resource "aws_cloudwatch_log_group" "lambda_rotation_master" {
  name              = "/aws/lambda/${var.project_name}-rotation-master"
  retention_in_days = 14
  tags              = { Name = "${var.project_name}-lambda-rotation-master-logs" }
}

resource "aws_cloudwatch_log_group" "lambda_rotation_worker" {
  name              = "/aws/lambda/${var.project_name}-rotation-worker"
  retention_in_days = 14
  tags              = { Name = "${var.project_name}-lambda-rotation-worker-logs" }
}

resource "aws_lambda_function" "logs_consumer" {
  function_name    = "${var.project_name}-logs-consumer"
  role             = aws_iam_role.lambda_consumer.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.consumer_timeout
  memory_size      = var.consumer_memory
  filename         = local.consumer_zip
  source_code_hash = filebase64sha256(local.consumer_zip)

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DB_HOST     = aws_instance.questdb.private_ip
      DB_PORT     = "8812"
      DB_NAME     = var.questdb_pg_database
      DB_USER     = var.questdb_pg_user
      DB_PASSWORD = var.questdb_pg_password
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_consumer,
    aws_iam_role_policy.lambda_consumer_sqs,
    aws_iam_role_policy.lambda_consumer_logs,
    aws_iam_role_policy.lambda_consumer_vpc,
    aws_instance.questdb,
  ]

  tags = { Name = "${var.project_name}-logs-consumer" }
}

resource "aws_lambda_event_source_mapping" "logs_consumer" {
  event_source_arn                   = aws_sqs_queue.logs.arn
  function_name                      = aws_lambda_function.logs_consumer.arn
  batch_size                         = var.consumer_batch_size
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
}

resource "aws_lambda_function" "rotation_master" {
  function_name    = "${var.project_name}-rotation-master"
  role             = aws_iam_role.lambda_rotation.arn
  handler          = "rotation_master.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_master_timeout
  memory_size      = var.lambda_master_memory
  filename         = local.rotation_master_zip
  source_code_hash = filebase64sha256(local.rotation_master_zip)

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      MONGODB_URL            = local.mongodb_url
      MONGO_DB               = var.mongo_db_name
      SQS_QUEUE_URL          = aws_sqs_queue.rotation.id
      ROTATION_INTERVAL_DAYS = tostring(var.rotation_interval_days)
      ENVIRONMENT            = var.environment
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_rotation_master,
    aws_iam_role_policy.lambda_rotation_sqs,
    aws_iam_role_policy.lambda_rotation_logs,
    aws_iam_role_policy.lambda_rotation_vpc,
    aws_sqs_queue.rotation,
  ]

  tags = { Name = "${var.project_name}-rotation-master" }
}

resource "aws_lambda_function" "rotation_worker" {
  function_name    = "${var.project_name}-rotation-worker"
  role             = aws_iam_role.lambda_rotation.arn
  handler          = "rotation_worker.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_worker_timeout
  memory_size      = var.lambda_worker_memory
  filename         = local.rotation_worker_zip
  source_code_hash = filebase64sha256(local.rotation_worker_zip)

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      API_BASE_URL       = local.api_base_url
      ROTATION_API_TOKEN = var.rotation_api_token
      ENVIRONMENT        = var.environment
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_rotation_worker,
    aws_iam_role_policy.lambda_rotation_sqs,
    aws_iam_role_policy.lambda_rotation_logs,
    aws_iam_role_policy.lambda_rotation_vpc,
    aws_sqs_queue.rotation,
    aws_lb.main,
  ]

  tags = { Name = "${var.project_name}-rotation-worker" }
}

resource "aws_lambda_event_source_mapping" "rotation_worker" {
  event_source_arn        = aws_sqs_queue.rotation.arn
  function_name           = aws_lambda_function.rotation_worker.arn
  batch_size              = 1
  enabled                 = true
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_cloudwatch_event_rule" "rotation_schedule" {
  name                = "${var.project_name}-rotation-schedule"
  description         = "Chequeo diario de rotacion de llaves de cifrado"
  schedule_expression = var.rotation_schedule
  state               = "ENABLED"

  tags = { Name = "${var.project_name}-rotation-schedule" }
}

resource "aws_cloudwatch_event_target" "rotation_master" {
  rule      = aws_cloudwatch_event_rule.rotation_schedule.name
  target_id = "RotationMasterLambda"
  arn       = aws_lambda_function.rotation_master.arn

  input = jsonencode({
    source    = "eventbridge"
    triggered = true
  })
}

resource "aws_lambda_permission" "eventbridge_rotation_master" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rotation_master.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rotation_schedule.arn
}

resource "aws_cloudwatch_metric_alarm" "lambda_consumer_errors" {
  alarm_name          = "${var.project_name}-lambda-consumer-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions        = { FunctionName = aws_lambda_function.logs_consumer.function_name }
  alarm_description = "Lambda consumer de logs tiene errores"
  tags              = { Name = "${var.project_name}-lambda-consumer-errors" }
}

resource "aws_cloudwatch_metric_alarm" "lambda_rotation_master_errors" {
  alarm_name          = "${var.project_name}-lambda-rotation-master-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions        = { FunctionName = aws_lambda_function.rotation_master.function_name }
  alarm_description = "Lambda rotation master tiene errores"
  tags              = { Name = "${var.project_name}-lambda-rotation-master-errors" }
}

resource "aws_cloudwatch_metric_alarm" "lambda_rotation_worker_errors" {
  alarm_name          = "${var.project_name}-lambda-rotation-worker-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions        = { FunctionName = aws_lambda_function.rotation_worker.function_name }
  alarm_description = "Lambda rotation worker tiene errores"
  tags              = { Name = "${var.project_name}-lambda-rotation-worker-errors" }
}
