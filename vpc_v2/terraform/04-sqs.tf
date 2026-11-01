# ============================================================================
# Grupo 4 — SQS (logs y rotación de llaves)
# ============================================================================

resource "aws_sqs_queue" "logs_dlq" {
  name                      = "${var.project_name}-logs-dlq"
  message_retention_seconds = var.sqs_logs_message_retention

  tags = { Name = "${var.project_name}-logs-dlq" }
}

resource "aws_sqs_queue" "logs" {
  name                       = "${var.project_name}-logs-queue"
  visibility_timeout_seconds = var.sqs_logs_visibility_timeout
  message_retention_seconds  = var.sqs_logs_message_retention

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.logs_dlq.arn
    maxReceiveCount     = var.sqs_logs_max_receive_count
  })

  tags = { Name = "${var.project_name}-logs-queue" }
}

resource "aws_sqs_queue" "rotation_dlq" {
  name                      = "${var.project_name}-rotation-dlq"
  message_retention_seconds = var.sqs_rotation_message_retention

  tags = { Name = "${var.project_name}-rotation-dlq" }
}

resource "aws_sqs_queue" "rotation" {
  name = "${var.project_name}-rotation-queue"
  # >= timeout del Lambda worker: evita reencolar mientras aun se procesa.
  visibility_timeout_seconds = var.lambda_worker_timeout
  message_retention_seconds  = var.sqs_rotation_message_retention

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.rotation_dlq.arn
    maxReceiveCount     = var.sqs_rotation_max_receive_count
  })

  tags = { Name = "${var.project_name}-rotation-queue" }
}

resource "aws_cloudwatch_metric_alarm" "logs_dlq_messages" {
  alarm_name          = "${var.project_name}-logs-dlq-messages"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions        = { QueueName = aws_sqs_queue.logs_dlq.name }
  alarm_description = "Mensajes en la DLQ de logs — el consumer fallo repetidamente"
  tags              = { Name = "${var.project_name}-logs-dlq-alarm" }
}

resource "aws_cloudwatch_metric_alarm" "rotation_dlq_messages" {
  alarm_name          = "${var.project_name}-rotation-dlq-messages"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions        = { QueueName = aws_sqs_queue.rotation_dlq.name }
  alarm_description = "Mensajes en la DLQ de rotacion — el worker fallo repetidamente"
  tags              = { Name = "${var.project_name}-rotation-dlq-alarm" }
}
