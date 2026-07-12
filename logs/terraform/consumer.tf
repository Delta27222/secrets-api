# ============================================================================
# Lambda consumidor: SQS (logs) -> QuestDB
#
# Disparada por la cola aws_sqs_queue.logs. Cada mensaje se inserta en la
# tabla `Logs` de QuestDB vía protocolo Postgres-wire (puerto 8812).
# Conecta a la IP pública fija (Elastic IP) de la EC2 de QuestDB.
# ============================================================================

data "aws_caller_identity" "current" {}

# ---- Empaquetado del código (build_consumer.sh genera el zip) ----
locals {
  consumer_zip = "${path.module}/lambda_consumer.zip"
}

# ---- IAM role de ejecución ----
resource "aws_iam_role" "consumer" {
  name = "${local.name}-consumer-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Logs de la propia Lambda -> CloudWatch
resource "aws_iam_role_policy_attachment" "consumer_basic" {
  role       = aws_iam_role.consumer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Permisos para consumir de la cola SQS de logs
resource "aws_iam_role_policy" "consumer_sqs" {
  name = "${local.name}-consumer-sqs"
  role = aws_iam_role.consumer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
      ]
      Resource = aws_sqs_queue.logs.arn
    }]
  })
}

# ---- Función Lambda ----
resource "aws_lambda_function" "consumer" {
  function_name    = "${local.name}-consumer"
  role             = aws_iam_role.consumer.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.consumer_timeout
  memory_size      = var.consumer_memory
  filename         = local.consumer_zip
  source_code_hash = filebase64sha256(local.consumer_zip)

  environment {
    variables = {
      DB_HOST     = aws_eip.questdb.public_ip
      DB_PORT     = "8812"
      DB_NAME     = var.questdb_pg_database
      DB_USER     = var.questdb_pg_user
      DB_PASSWORD = var.questdb_pg_password
    }
  }

  # No arrancar hasta que la EIP esté asociada a la EC2
  depends_on = [aws_eip.questdb]
}

# ---- Event source mapping: SQS -> Lambda ----
resource "aws_lambda_event_source_mapping" "consumer" {
  event_source_arn                   = aws_sqs_queue.logs.arn
  function_name                      = aws_lambda_function.consumer.arn
  batch_size                         = var.consumer_batch_size
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
}
