# ============================================================================
# Variables — Infraestructura de LOGS (QuestDB)
# ============================================================================

variable "aws_region" {
  description = "Región AWS"
  type        = string
  default     = "us-east-1"
}

variable "availability_zone" {
  description = "AZ donde viven la EC2 y el volumen EBS (deben coincidir)"
  type        = string
  default     = "us-east-1a"
}

variable "project_name" {
  description = "Prefijo de nombres"
  type        = string
  default     = "tek-secrets"
}

variable "environment" {
  description = "Ambiente (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# ---- EC2 / QuestDB ----
variable "instance_type" {
  description = "Tipo de instancia EC2"
  type        = string
  default     = "t3.small" # 2 vCPU / 2 GB; subir a t3.medium si crecen los logs
}

variable "ami_id" {
  description = "AMI a usar (vacío = Amazon Linux 2023 más reciente)"
  type        = string
  default     = ""
}

variable "key_name" {
  description = "Nombre del key pair EC2 para SSH (vacío = sin SSH por llave)"
  type        = string
  default     = ""
}

variable "questdb_version" {
  description = "Tag de la imagen Docker de QuestDB"
  type        = string
  default     = "8.1.1"
}

variable "root_volume_size" {
  description = "Tamaño del disco raíz (GB)"
  type        = number
  default     = 20
}

variable "data_volume_size" {
  description = "Tamaño del volumen EBS de datos de QuestDB (GB)"
  type        = number
  default     = 20
}

# ---- Red / acceso ----
variable "allowed_cidr" {
  description = "CIDRs permitidos a los puertos de QuestDB. Idealmente la IP de la API, no 0.0.0.0/0"
  type        = list(string)
  default     = ["0.0.0.0/0"] # ⚠️ restringir en producción
}

variable "ssh_cidr" {
  description = "CIDR permitido a SSH (vacío = SSH cerrado)"
  type        = string
  default     = ""
}

# ---- Lambda consumidor (SQS -> QuestDB) ----
variable "consumer_timeout" {
  description = "Timeout de la Lambda consumidora (segundos)"
  type        = number
  default     = 30
}

variable "consumer_memory" {
  description = "Memoria de la Lambda consumidora (MB)"
  type        = number
  default     = 128
}

variable "consumer_batch_size" {
  description = "Mensajes SQS por invocación de la Lambda"
  type        = number
  default     = 10
}

variable "questdb_pg_user" {
  description = "Usuario del protocolo Postgres-wire de QuestDB"
  type        = string
  default     = "admin"
}

variable "questdb_pg_password" {
  description = "Password del protocolo Postgres-wire de QuestDB"
  type        = string
  default     = "quest"
  sensitive   = true
}

variable "questdb_pg_database" {
  description = "Base de datos PG de QuestDB"
  type        = string
  default     = "qdb"
}

# ---- SQS ----
variable "sqs_visibility_timeout" {
  description = "SQS visibility timeout (segundos). Debe ser >= consumer_timeout."
  type        = number
  default     = 60
}

variable "sqs_message_retention" {
  description = "SQS retención de mensajes (segundos)"
  type        = number
  default     = 345600 # 4 días
}

variable "sqs_max_receive_count" {
  description = "Reintentos antes de mandar a la DLQ"
  type        = number
  default     = 5
}
