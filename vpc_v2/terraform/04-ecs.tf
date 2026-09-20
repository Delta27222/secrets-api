# ============================================================================
# Grupo 4 — ECS Fargate
#
# Seguridad del contenedor: FS de solo lectura, user 1000:1000 (no root),
# sin privilegios, todas las Linux capabilities eliminadas. Secretos vienen
# de Secrets Manager (grupo 4), nunca como env var plana.
# ============================================================================

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${var.project_name}-cluster" }
}

# Sin depends_on hacia el servicio: la relación va en la otra dirección
# (ver aws_ecs_service.api). Un depends_on aqui apuntando al servicio hacia
# ADELANTE en el grafo se destruye ANTES que el servicio (Terraform destruye
# en orden inverso al de creacion) — exactamente lo opuesto de lo que exige
# AWS ("capacity provider en uso, no se puede quitar mientras el servicio
# lo referencia"). Real, no teórico: nos pasó en un destroy.
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

resource "aws_cloudwatch_log_group" "ecs_api" {
  name              = "/ecs/${var.project_name}-api"
  retention_in_days = 30

  tags = { Name = "${var.project_name}-ecs-api-logs" }
}

# Diferida desde el grupo 2 — el log group recien se crea aqui.
resource "aws_iam_role_policy" "ecs_execution_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.ecs_api.arn}:*"
    }]
  })
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
      essential = true

      portMappings = [{ containerPort = 8000, protocol = "tcp" }]

      readonlyRootFilesystem = true
      user                   = "1000:1000"
      privileged             = false

      linuxParameters = {
        capabilities = { drop = ["ALL"], add = [] }
        tmpfs        = [{ containerPath = "/tmp", size = 64 }]
      }

      environment = [
        { name = "MONGO_DB", value = var.mongo_db_name },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "EC2_INSTANCE_IP", value = aws_instance.questdb.private_ip },
        { name = "EC2_INSTANCE_PORT", value = "9000" },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "PYTHONUNBUFFERED", value = "1" },
        { name = "PYTHONDONTWRITEBYTECODE", value = "1" },
        { name = "GITHUB_ORG_NAME", value = var.github_org_name }
      ]

      secrets = [
        { name = "MONGODB_URL", valueFrom = aws_secretsmanager_secret.mongodb_url.arn },
        { name = "SECRET_KEY", valueFrom = aws_secretsmanager_secret.secret_key.arn },
        { name = "MONGODB_CSFLE_MASTER_KEY", valueFrom = aws_secretsmanager_secret.csfle_master_key.arn },
        { name = "GITHUB_CLIENT_ID", valueFrom = aws_secretsmanager_secret.github_client_id.arn },
        { name = "GITHUB_CLIENT_SECRET", valueFrom = aws_secretsmanager_secret.github_client_secret.arn }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }

      ulimits = [{ name = "nofile", softLimit = 1024, hardLimit = 4096 }]
    }
  ])

  tags = { Name = "${var.project_name}-task-def-api" }
}

resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-api-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.ecs_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = var.ecs_desired_count
  }

  network_configuration {
    subnets          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [
    aws_lb_listener.http_redirect,
    aws_iam_role_policy.ecs_execution_ecr,
    aws_iam_role_policy.ecs_execution_logs,
    aws_iam_role_policy.ecs_execution_secrets,
    aws_instance.questdb,
    null_resource.api_image,
    # Dirección correcta para que el destroy funcione: el servicio (que
    # depende de esto) se destruye ANTES que los capacity providers,
    # liberándolos antes de que Terraform intente quitarlos del cluster.
    aws_ecs_cluster_capacity_providers.main,
  ]

  tags = { Name = "${var.project_name}-api-service" }
}

# Forzar redeploy cuando cambia la imagen — sin esto, un `docker push` al
# mismo tag no reinicia las tareas (el task definition no cambió).
resource "null_resource" "ecs_force_redeploy" {
  triggers = {
    image_hash = local.api_source_hash
  }

  provisioner "local-exec" {
    command = "aws ecs update-service --cluster ${aws_ecs_cluster.main.name} --service ${aws_ecs_service.api.name} --force-new-deployment --region ${var.aws_region} >/dev/null"
  }

  depends_on = [aws_ecs_service.api, null_resource.api_image]
}

resource "aws_appautoscaling_target" "ecs_api" {
  max_capacity       = var.ecs_max_count
  min_capacity       = var.ecs_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "ecs_scale_up_cpu" {
  name               = "${var.project_name}-scale-up-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_api.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${var.project_name}-ecs-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }

  alarm_description  = "CPU del servicio ECS supera el 80%"
  treat_missing_data = "notBreaching"
  tags               = { Name = "${var.project_name}-ecs-cpu-alarm" }
}

resource "aws_cloudwatch_metric_alarm" "ecs_running_tasks_low" {
  alarm_name          = "${var.project_name}-ecs-tasks-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = 60
  statistic           = "Average"
  threshold           = var.ecs_desired_count

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }

  alarm_description  = "El numero de tareas ECS en ejecucion cayo por debajo del minimo deseado"
  treat_missing_data = "breaching"
  tags               = { Name = "${var.project_name}-ecs-tasks-alarm" }
}
