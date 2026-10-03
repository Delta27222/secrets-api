# ============================================================================
# Outputs — se agregan por grupo conforme se construye vpc_v2.
# Grupo 1 (Red)
# ============================================================================

output "vpc_id" {
  value = aws_vpc.main.id
}

output "vpc_cidr" {
  value = aws_vpc.main.cidr_block
}

output "public_subnet_ids" {
  value = [aws_subnet.public_a.id, aws_subnet.public_b.id]
}

output "private_subnet_ids" {
  value = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "private_data_subnet_ids" {
  value = [aws_subnet.private_data_a.id, aws_subnet.private_data_b.id]
}

output "internet_gateway_id" {
  value = aws_internet_gateway.main.id
}

output "nat_gateway_id" {
  value = aws_nat_gateway.main.id
}

output "nat_gateway_public_ip" {
  value = aws_eip.nat.public_ip
}

# ============================================================================
# Grupo 2 (Seguridad/IAM)
# ============================================================================

output "security_group_ids" {
  value = {
    alb           = aws_security_group.alb.id
    ecs           = aws_security_group.ecs.id
    questdb       = aws_security_group.questdb.id
    mongodb       = aws_security_group.mongodb.id
    lambda        = aws_security_group.lambda.id
    vpc_endpoints = aws_security_group.vpc_endpoints.id
  }
}

output "iam_role_arns" {
  value = {
    ecs_execution   = aws_iam_role.ecs_execution.arn
    ecs_task        = aws_iam_role.ecs_task.arn
    lambda_consumer = aws_iam_role.lambda_consumer.arn
    lambda_rotation = aws_iam_role.lambda_rotation.arn
    ec2_data        = aws_iam_role.ec2_data.arn
  }
}

output "ec2_data_instance_profile" {
  value = aws_iam_instance_profile.ec2_data.name
}

# ============================================================================
# Grupo 3 (Datos)
# ============================================================================

output "docker_ami_id" {
  value = data.aws_ami.docker.id
}

output "ecr_repository_urls" {
  value = {
    api     = aws_ecr_repository.api.repository_url
    questdb = aws_ecr_repository.questdb.repository_url
    mongodb = aws_ecr_repository.mongodb.repository_url
  }
}

output "questdb_primary_instance_id" {
  value = aws_instance.questdb.id
}

output "questdb_standby_instance_id" {
  value = aws_instance.questdb_standby.id
}

output "mongodb_primary_instance_id" {
  value = aws_instance.mongodb_primary.id
}

output "mongodb_secondary_instance_id" {
  value = aws_instance.mongodb_secondary.id
}

output "mongodb_arbiter_instance_id" {
  value = aws_instance.mongodb_arbiter.id
}

output "mongodb_connection_string_hint" {
  value = "mongodb://${var.mongodb_admin_user}:<password>@${var.mongodb_primary_ip}:27017,${var.mongodb_secondary_ip}:27017/?replicaSet=${var.mongodb_replica_set_name}&authSource=admin"
}

# ============================================================================
# Grupo 4 (App: ALB + ECS + SQS + Lambda)
# ============================================================================

output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "api_url" {
  value = local.api_base_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "sqs_queue_urls" {
  value = {
    logs     = aws_sqs_queue.logs.id
    rotation = aws_sqs_queue.rotation.id
  }
}

output "lambda_function_names" {
  value = {
    logs_consumer   = aws_lambda_function.logs_consumer.function_name
    rotation_master = aws_lambda_function.rotation_master.function_name
    rotation_worker = aws_lambda_function.rotation_worker.function_name
  }
}

# ============================================================================
# Front + dominio propio
# ============================================================================

output "front_ecr_repository_url" {
  value = aws_ecr_repository.front.repository_url
}

output "front_service_name" {
  value = aws_ecs_service.front.name
}

output "github_actions_role_arn" {
  description = "role-to-assume del workflow de GitHub Actions del front (aws-actions/configure-aws-credentials)"
  value       = aws_iam_role.github_actions_front.arn
}

output "acm_validation_records" {
  description = "Si no aparece: falta var.domain_name. Pegar este CNAME en GoDaddy para validar el certificado."
  value = var.domain_name != "" ? {
    name  = tolist(aws_acm_certificate.main[0].domain_validation_options)[0].resource_record_name
    type  = tolist(aws_acm_certificate.main[0].domain_validation_options)[0].resource_record_type
    value = tolist(aws_acm_certificate.main[0].domain_validation_options)[0].resource_record_value
  } : null
}

output "dns_records_needed" {
  description = "CNAMEs a crear en GoDaddy una vez que el certificado valide"
  value = var.domain_name != "" ? {
    app = { name = "app.${var.domain_name}", type = "CNAME", value = aws_lb.main.dns_name }
    api = { name = "api.${var.domain_name}", type = "CNAME", value = aws_lb.main.dns_name }
  } : null
}

output "app_url" {
  value = var.domain_name != "" ? "https://app.${var.domain_name}" : null
}
