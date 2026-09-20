# ============================================================================
# Variables — se agregan por grupo conforme se construye vpc_v2.
# Grupo 1 (Red): aws_region..subnet_private_data_b_cidr
# ============================================================================

variable "aws_region" {
  description = "Región AWS donde se despliega toda la arquitectura"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefijo para nombrar todos los recursos"
  type        = string
  default     = "tek-secrets-v2"
}

variable "environment" {
  description = "Ambiente de despliegue (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "El ambiente debe ser dev, staging o prod."
  }
}

variable "vpc_cidr" {
  description = "CIDR block de la VPC. Debe ser un bloque /16 privado RFC 1918."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_public_a_cidr" {
  description = "CIDR de la subred pública en AZ 'a' (ALB nodo A, NAT Gateway)"
  type        = string
  default     = "10.0.1.0/24"
}

variable "subnet_public_b_cidr" {
  description = "CIDR de la subred pública en AZ 'b' (ALB nodo B)"
  type        = string
  default     = "10.0.2.0/24"
}

variable "subnet_private_a_cidr" {
  description = "CIDR de la subred privada de apps en AZ 'a' (ECS tasks, Lambda)"
  type        = string
  default     = "10.0.3.0/24"
}

variable "subnet_private_b_cidr" {
  description = "CIDR de la subred privada de apps en AZ 'b' (ECS tasks, Lambda, MongoDB Arbiter)"
  type        = string
  default     = "10.0.4.0/24"
}

variable "subnet_private_data_a_cidr" {
  description = "CIDR de la subred privada de datos en AZ 'a' (QuestDB primary, MongoDB primary). Sin ruta a internet."
  type        = string
  default     = "10.0.5.0/24"
}

variable "subnet_private_data_b_cidr" {
  description = "CIDR de la subred privada de datos en AZ 'b' (QuestDB standby, MongoDB secondary). Sin ruta a internet."
  type        = string
  default     = "10.0.6.0/24"
}

# ---- Grupo 3: QuestDB ----

variable "questdb_instance_type" {
  description = "Tipo de instancia EC2 para QuestDB Primary y Standby"
  type        = string
  default     = "t3.small"
}

variable "questdb_version" {
  description = "Tag de la imagen Docker de QuestDB (mirror a ECR)"
  type        = string
  default     = "8.1.1"
}

variable "questdb_data_volume_size" {
  description = "Tamaño del volumen EBS de datos de QuestDB (GB)"
  type        = number
  default     = 40
}

variable "questdb_pg_user" {
  description = "Usuario del protocolo Postgres-wire de QuestDB"
  type        = string
  default     = "admin"
}

variable "questdb_pg_database" {
  description = "Base de datos PG de QuestDB"
  type        = string
  default     = "qdb"
}

variable "questdb_pg_password" {
  description = "Contraseña del protocolo Postgres-wire de QuestDB. Genera con: openssl rand -base64 24"
  type        = string
  sensitive   = true
}

variable "questdb_primary_ip" {
  description = "IP privada fija del QuestDB Primary en private-data-a"
  type        = string
  default     = "10.0.5.20"
}

variable "questdb_standby_ip" {
  description = "IP privada fija del QuestDB Standby en private-data-b"
  type        = string
  default     = "10.0.6.20"
}

# ---- Grupo 3: MongoDB ----

variable "mongodb_instance_type" {
  description = "Tipo de instancia EC2 para MongoDB Primary y Secondary"
  type        = string
  default     = "t3.medium"
}

variable "mongodb_arbiter_instance_type" {
  description = "Tipo de instancia EC2 para el MongoDB Arbiter (no almacena datos)"
  type        = string
  default     = "t3.micro"
}

variable "mongodb_version" {
  description = "Tag de la imagen Docker de MongoDB (mirror a ECR)"
  type        = string
  default     = "7.0"
}

variable "mongodb_admin_user" {
  description = "Usuario administrador de MongoDB"
  type        = string
  default     = "admin"
}

variable "mongodb_admin_password" {
  description = "Contraseña del administrador de MongoDB. Genera con: openssl rand -base64 32"
  type        = string
  sensitive   = true
}

variable "mongodb_replica_set_name" {
  description = "Nombre del Replica Set (debe coincidir en los 3 nodos)"
  type        = string
  default     = "rs0"
}

variable "mongodb_data_volume_size" {
  description = "Tamaño del volumen EBS de datos de MongoDB Primary y Secondary (GB)"
  type        = number
  default     = 30
}

variable "mongodb_primary_ip" {
  description = "IP privada fija del MongoDB Primary en private-data-a"
  type        = string
  default     = "10.0.5.10"
}

variable "mongodb_secondary_ip" {
  description = "IP privada fija del MongoDB Secondary en private-data-b"
  type        = string
  default     = "10.0.6.10"
}

variable "mongodb_arbiter_ip" {
  description = "IP privada fija del MongoDB Arbiter en private-apps-b"
  type        = string
  default     = "10.0.4.50"
}

# ---- Grupo 4: App (ALB, ECS, SQS, Lambda) ----

variable "mongo_db_name" {
  description = "Nombre de la base de datos MongoDB"
  type        = string
  default     = "secrets-27222"
}

variable "acm_certificate_arn" {
  description = "ARN del certificado ACM para HTTPS del ALB. Vacio = HTTP directo (tesis/dev)."
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Dominio de la API (ej. api.teksecrets.com). Vacio = usar el DNS del ALB."
  type        = string
  default     = ""
}

variable "api_image_tag" {
  description = "Tag de la imagen de la API en ECR"
  type        = string
  default     = "latest"
}

variable "ecs_task_cpu" {
  description = "CPU de la tarea ECS (256 = 0.25 vCPU, 512 = 0.5 vCPU)"
  type        = number
  default     = 512
}

variable "ecs_task_memory" {
  description = "Memoria de la tarea ECS en MB"
  type        = number
  default     = 1024
}

variable "ecs_desired_count" {
  description = "Numero deseado de tareas ECS en ejecucion"
  type        = number
  default     = 1
}

variable "ecs_max_count" {
  description = "Numero maximo de tareas ECS (limite de autoscaling)"
  type        = number
  default     = 2
}

variable "github_client_id" {
  description = "GitHub OAuth App Client ID. Login falla hasta que se configure un valor real (Secrets Manager rechaza string vacio)."
  type        = string
  default     = "CHANGEME_github_client_id"
}

variable "github_client_secret" {
  description = "GitHub OAuth App Client Secret. Login falla hasta que se configure un valor real (Secrets Manager rechaza string vacio)."
  type        = string
  default     = "CHANGEME_github_client_secret"
  sensitive   = true
}

variable "rotation_api_token" {
  description = "Token de servicio (tok_...) para que la Lambda worker autentique contra la API. Actualizar tras el primer deploy con un token real emitido por la API."
  type        = string
  default     = "tok_placeholder_update_after_deploy"
  sensitive   = true
}

variable "rotation_interval_days" {
  description = "Dias que debe cumplir una llave activa antes de ser rotada"
  type        = number
  default     = 90
}

variable "rotation_schedule" {
  description = "Cron de EventBridge para el chequeo de rotacion"
  type        = string
  default     = "cron(0 0 * * ? *)"
}

variable "consumer_timeout" {
  description = "Timeout de la Lambda consumer de logs (segundos)"
  type        = number
  default     = 30
}

variable "consumer_memory" {
  description = "Memoria de la Lambda consumer de logs (MB)"
  type        = number
  default     = 128
}

variable "consumer_batch_size" {
  description = "Mensajes SQS por invocacion del consumer"
  type        = number
  default     = 10
}

variable "lambda_master_timeout" {
  description = "Timeout de la Lambda rotation-master (segundos)"
  type        = number
  default     = 60
}

variable "lambda_master_memory" {
  description = "Memoria de la Lambda rotation-master (MB)"
  type        = number
  default     = 256
}

variable "lambda_worker_timeout" {
  description = "Timeout de la Lambda rotation-worker (segundos)"
  type        = number
  default     = 900
}

variable "lambda_worker_memory" {
  description = "Memoria de la Lambda rotation-worker (MB)"
  type        = number
  default     = 512
}

variable "sqs_logs_visibility_timeout" {
  description = "SQS visibility timeout de la cola de logs (segundos)"
  type        = number
  default     = 60
}

variable "sqs_logs_message_retention" {
  description = "Retencion de mensajes en la cola de logs (segundos)"
  type        = number
  default     = 345600
}

variable "sqs_logs_max_receive_count" {
  description = "Reintentos antes de enviar a la DLQ de logs"
  type        = number
  default     = 5
}

variable "sqs_rotation_message_retention" {
  description = "Retencion de mensajes en la cola de rotacion (segundos)"
  type        = number
  default     = 86400
}

variable "sqs_rotation_max_receive_count" {
  description = "Reintentos antes de enviar a la DLQ de rotacion"
  type        = number
  default     = 3
}

# ---- Grupo 5: Backup ----

variable "backup_retention_days" {
  description = "Dias de retencion de los snapshots de AWS Backup. RPO=6h, retencion=7 dias -> 28 puntos de recuperacion."
  type        = number
  default     = 7
}
