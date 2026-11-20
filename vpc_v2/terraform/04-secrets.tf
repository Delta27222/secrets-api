# ============================================================================
# Grupo 4 — Secrets Manager
#
# El diseño viejo creaba estos secretos por fuera de Terraform (deploy.sh
# leía secrets.env y los subía con AWS CLI), y ecs.tf referenciaba sus ARNs
# HARDCODEADOS a mano (cuenta + sufijo del proyecto original). Aquí son
# recursos de Terraform: se crean, actualizan y destruyen con el resto.
#
# secret_key y csfle_master_key se generan solos (ambiente nuevo, sin datos
# que migrar — no hay compatibilidad que preservar). github_client_id/secret
# sí son externos (OAuth App de GitHub) y quedan en blanco hasta que se
# configuren valores reales en terraform.tfvars.
# ============================================================================

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "csfle_master_key" {
  # La app decodifica esta key en base64 y exige exactamente 96 bytes.
  # 128 caracteres base64 (sin padding) -> 128/4*3 = 96 bytes.
  length  = 128
  special = false
}

locals {
  # urlencode() es obligatorio aqui: una password base64 (openssl rand
  # -base64) puede traer '/', '+' o '=', y pymongo rompe el parseo de
  # host:puerto si el usuario/password no vienen escapados (RFC 3986).
  mongodb_url = "mongodb://${urlencode(var.mongodb_admin_user)}:${urlencode(var.mongodb_admin_password)}@${var.mongodb_primary_ip}:27017,${var.mongodb_secondary_ip}:27017/${var.mongo_db_name}?replicaSet=${var.mongodb_replica_set_name}&authSource=admin"
}

resource "aws_secretsmanager_secret" "mongodb_url" {
  name                    = "${var.project_name}/mongodb-url"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-mongodb-url" }
}

resource "aws_secretsmanager_secret_version" "mongodb_url" {
  secret_id     = aws_secretsmanager_secret.mongodb_url.id
  secret_string = local.mongodb_url
}

resource "aws_secretsmanager_secret" "secret_key" {
  name                    = "${var.project_name}/secret-key"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-secret-key" }
}

resource "aws_secretsmanager_secret_version" "secret_key" {
  secret_id     = aws_secretsmanager_secret.secret_key.id
  secret_string = random_password.secret_key.result
}

resource "aws_secretsmanager_secret" "csfle_master_key" {
  name                    = "${var.project_name}/csfle-master-key"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-csfle-master-key" }
}

resource "aws_secretsmanager_secret_version" "csfle_master_key" {
  secret_id     = aws_secretsmanager_secret.csfle_master_key.id
  secret_string = random_password.csfle_master_key.result
}

resource "aws_secretsmanager_secret" "github_client_id" {
  name                    = "${var.project_name}/github-client-id"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-github-client-id" }
}

resource "aws_secretsmanager_secret_version" "github_client_id" {
  secret_id     = aws_secretsmanager_secret.github_client_id.id
  secret_string = var.github_client_id
}

resource "aws_secretsmanager_secret" "github_client_secret" {
  name                    = "${var.project_name}/github-client-secret"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-github-client-secret" }
}

resource "aws_secretsmanager_secret_version" "github_client_secret" {
  secret_id     = aws_secretsmanager_secret.github_client_secret.id
  secret_string = var.github_client_secret
}

# Firma las cookies/JWT de NextAuth en el front. Igual que secret_key y
# csfle_master_key: ambiente nuevo, se genera solo, sin nada que migrar.
resource "random_password" "nextauth_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "sdk_demo_token" {
  name                    = "${var.project_name}/sdk-demo-token"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-sdk-demo-token" }
}

resource "aws_secretsmanager_secret_version" "sdk_demo_token" {
  secret_id     = aws_secretsmanager_secret.sdk_demo_token.id
  secret_string = var.sdk_demo_token
}

resource "aws_secretsmanager_secret" "nextauth_secret" {
  name                    = "${var.project_name}/nextauth-secret"
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project_name}-secret-nextauth-secret" }
}

resource "aws_secretsmanager_secret_version" "nextauth_secret" {
  secret_id     = aws_secretsmanager_secret.nextauth_secret.id
  secret_string = random_password.nextauth_secret.result
}
