# ============================================================================
# Terraform Variables para Rotation + Reencryptación Lambda
# ============================================================================

variable "aws_region" {
  description = "Región AWS"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Nombre del proyecto"
  type        = string
  default     = "tek-secrets"
}

variable "environment" {
  description = "Ambiente (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# ============================================================================
# MongoDB Configuration
# ============================================================================

variable "mongodb_url" {
  description = "MongoDB connection string"
  type        = string
  sensitive   = true
}

variable "mongo_db" {
  description = "Nombre base de datos MongoDB"
  type        = string
  default     = "db_name"
}

# ============================================================================
# API (Render) - el Lambda Worker delega la rotación aquí (CSFLE nativo)
# ============================================================================

variable "api_base_url" {
  description = "URL base de la API en Render (ej: https://api.com)"
  type        = string
}

variable "rotation_api_token" {
  description = "Service token de sistema (tok_..., scope keys:rotate) para autenticar el Lambda→API (header Authorization: Bearer)"
  type        = string
  sensitive   = true
}

# ============================================================================
# QuestDB Configuration (opcional, para logging auditoría)
# ============================================================================

variable "questdb_ip" {
  description = "IP EC2 instancia QuestDB"
  type        = string
  default     = ""
}

variable "questdb_port" {
  description = "Puerto QuestDB"
  type        = string
  default     = ""
}

# ============================================================================
# Lambda Configuration
# ============================================================================

variable "lambda_master_memory" {
  description = "Memory para Lambda Maestro (MB)"
  type        = number
  default     = 256
}

variable "lambda_master_timeout" {
  description = "Timeout para Lambda Maestro (segundos)"
  type        = number
  default     = 60
}

variable "lambda_worker_memory" {
  description = "Memory para Lambda Worker (MB)"
  type        = number
  default     = 512
}

variable "lambda_worker_timeout" {
  description = "Timeout para Lambda Worker (segundos)"
  type        = number
  default     = 900  # 15 minutos
}

# ============================================================================
# EventBridge Schedule
# ============================================================================

variable "rotation_schedule" {
  description = "Cron expression para el CHEQUEO de rotación (formato EventBridge)"
  type        = string
  default     = "cron(0 0 * * ? *)"  # 00:00 UTC diariamente
}

variable "rotation_interval_days" {
  description = "Días que debe cumplir la llave activa antes de rotar (el Maestro revisa secrets_encryption.encrypted_at)"
  type        = number
  default     = 90
}

variable "rotation_schedule_description" {
  description = "Descripción del schedule"
  type        = string
  default     = "Rotación diaria de llaves de encriptación a las 00:00 UTC"
}

# ============================================================================
# SQS Configuration
# ============================================================================

variable "sqs_visibility_timeout" {
  description = "SQS visibility timeout (segundos)"
  type        = number
  default     = 900  # 15 minutos
}

variable "sqs_message_retention" {
  description = "SQS message retention (segundos)"
  type        = number
  default     = 86400  # 1 día
}

variable "sqs_max_receive_count" {
  description = "Máximo reintentos antes de enviar a DLQ"
  type        = number
  default     = 3
}

variable "sqs_batch_size" {
  description = "Batch size para Lambda consumer"
  type        = number
  default     = 1
}

# ============================================================================
# Tagging
# ============================================================================

variable "tags" {
  description = "Tags a aplicar a todos los recursos"
  type        = map(string)
  default = {
    Environment = "prod"
    Project     = "tek-secrets"
    ManagedBy   = "terraform"
    Purpose     = "encryption-key-rotation"
  }
}
