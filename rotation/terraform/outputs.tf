# ============================================================================
# Terraform Outputs
# ============================================================================

output "sqs_queue_url" {
  description = "URL de la SQS Queue"
  value       = aws_sqs_queue.rotation_queue.url
}

output "sqs_queue_arn" {
  description = "ARN de la SQS Queue"
  value       = aws_sqs_queue.rotation_queue.arn
}

output "sqs_dlq_url" {
  description = "URL de la SQS DLQ (Dead Letter Queue)"
  value       = aws_sqs_queue.rotation_dlq.url
}

output "lambda_master_arn" {
  description = "ARN de Lambda Maestro"
  value       = aws_lambda_function.rotation_master.arn
}

output "lambda_master_name" {
  description = "Nombre de Lambda Maestro"
  value       = aws_lambda_function.rotation_master.function_name
}

output "lambda_worker_arn" {
  description = "ARN de Lambda Worker"
  value       = aws_lambda_function.rotation_worker.arn
}

output "lambda_worker_name" {
  description = "Nombre de Lambda Worker"
  value       = aws_lambda_function.rotation_worker.function_name
}

output "eventbridge_rule_name" {
  description = "Nombre de la regla EventBridge"
  value       = aws_cloudwatch_event_rule.rotation_schedule.name
}

output "eventbridge_rule_arn" {
  description = "ARN de la regla EventBridge"
  value       = aws_cloudwatch_event_rule.rotation_schedule.arn
}

output "log_group_master" {
  description = "CloudWatch Log Group para Lambda Maestro"
  value       = aws_cloudwatch_log_group.lambda_master_logs.name
}

output "log_group_worker" {
  description = "CloudWatch Log Group para Lambda Worker"
  value       = aws_cloudwatch_log_group.lambda_worker_logs.name
}

# ============================================================================
# Información útil para monitoreo
# ============================================================================

output "cloudwatch_dashboard_url" {
  description = "URL para crear dashboard en CloudWatch"
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:"
}

output "lambda_logs_url_master" {
  description = "Enlace directo a logs de Lambda Maestro"
  value       = "https://console.aws.amazon.com/logs/home?region=${var.aws_region}#logStream:group=${aws_cloudwatch_log_group.lambda_master_logs.name}"
}

output "lambda_logs_url_worker" {
  description = "Enlace directo a logs de Lambda Worker"
  value       = "https://console.aws.amazon.com/logs/home?region=${var.aws_region}#logStream:group=${aws_cloudwatch_log_group.lambda_worker_logs.name}"
}

output "sqs_queue_console_url" {
  description = "Enlace directo a SQS Queue en AWS Console"
  value       = "https://console.aws.amazon.com/sqs/v3/home?region=${var.aws_region}#/queues/${aws_sqs_queue.rotation_queue.url}"
}

output "eventbridge_console_url" {
  description = "Enlace directo a EventBridge en AWS Console"
  value       = "https://console.aws.amazon.com/events/home?region=${var.aws_region}#/rules/${aws_cloudwatch_event_rule.rotation_schedule.name}"
}

# ============================================================================
# Información de costo
# ============================================================================

output "estimated_monthly_cost" {
  description = "Costo estimado mensual (aproximado)"
  value       = "Varia según volumen. Base: ~$0.50-1.50 USD/mes para <100 proyectos"
}

output "cost_breakdown" {
  description = "Desglose de costos"
  value = {
    "Lambda Maestro"     = "~$0.20 USD/mes (1 invocación diaria, muy rápido)"
    "Lambda Worker"      = "~$0.50-1.00 USD/mes (1 por proyecto, ~2-5s cada)"
    "SQS"                = "~$0.10 USD/mes (100 mensajes/día)"
    "CloudWatch Logs"    = "~$0.15 USD/mes (retention 14 días)"
    "Total aproximado"   = "$0.95-1.45 USD/mes"
  }
}
