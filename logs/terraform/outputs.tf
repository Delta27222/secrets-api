# ============================================================================
# Outputs — Infraestructura de LOGS (QuestDB)
# ============================================================================

output "questdb_public_ip" {
  description = "IP pública fija (Elastic IP) de QuestDB. Va en EC2_INSTANCE_IP de la API."
  value       = aws_eip.questdb.public_ip
}

output "questdb_web_console" {
  description = "URL de la consola web de QuestDB"
  value       = "http://${aws_eip.questdb.public_ip}:9000"
}

output "questdb_instance_id" {
  description = "ID de la instancia EC2"
  value       = aws_instance.questdb.id
}

output "logs_sqs_queue_url" {
  description = "URL de la cola SQS de logs (SQS_QUEUE_URL de la API)"
  value       = aws_sqs_queue.logs.id
}

output "logs_sqs_dlq_url" {
  description = "URL de la DLQ de logs"
  value       = aws_sqs_queue.logs_dlq.id
}

output "security_group_id" {
  description = "ID del Security Group de QuestDB"
  value       = aws_security_group.questdb.id
}

output "consumer_lambda_name" {
  description = "Nombre de la Lambda consumidora (SQS -> QuestDB)"
  value       = aws_lambda_function.consumer.function_name
}
