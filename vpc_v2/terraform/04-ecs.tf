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

  service_connect_defaults {
    namespace = aws_service_discovery_http_namespace.main.arn
  }

  tags = { Name = "${var.project_name}-cluster" }
}

# Namespace de Service Connect (Cloud Map "http", no DNS privado clasico):
# solo existe para que front resuelva "api:8000" sin salir de la VPC. No
# necesita asociarse a la VPC como un namespace de DNS privado normal —
# el proxy de Service Connect que ECS inyecta en cada task es quien
# resuelve y enruta.
resource "aws_service_discovery_http_namespace" "main" {
  name = "${var.project_name}.local"

  tags = { Name = "${var.project_name}-service-connect-ns" }
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

      portMappings = [{ name = "api", containerPort = 8000, protocol = "tcp" }]

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
        { name = "GITHUB_ORG_NAME", value = var.github_org_name },
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.logs.id }
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

  # Publica "api:8000" en el namespace de Service Connect — es lo que
  # deja a front llamarla como http://api:8000 sin salir de la VPC.
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn

    service {
      port_name      = "api"
      discovery_name = "api"

      client_alias {
        port     = 8000
        dns_name = "api"
      }
    }
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
    # ECS exige que el target group ya este asociado a un load balancer
    # ANTES de crear el service (si no, "does not have an associated load
    # balancer"). Cuando hay dominio, http_redirect deja de forward-ear a
    # tg.api (ahora redirige a HTTPS) — quien realmente lo asocia es el
    # listener HTTPS y/o su listener rule, asi que ambos tienen que estar
    # explicitos aca. Referencia sin indice ([0]) = "todas las instancias
    # de este recurso", valido aunque el count sea 0 (sin dominio).
    aws_lb_listener.http_redirect,
    aws_lb_listener.https,
    aws_lb_listener_rule.api_host,
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
# ============================================================================
# Front (Next.js) — task definition inicial + servicio.
#
# La imagen la construye y publica GitHub Actions (ver Q2/Q7), no
# Terraform: sin null_resource de build aca. En el primer apply el repo
# ECR esta vacio y el servicio queda con 0 tasks sanas hasta el primer
# push a main de secrets-app — es el orden esperado (infra primero, CI
# despues). lifecycle.ignore_changes evita que un apply posterior pise la
# revision de task definition que registro el ultimo deploy de CI.
# ============================================================================

resource "aws_iam_role" "ecs_task_front" {
  name        = "${var.project_name}-ecs-task-front-role"
  description = "Task role del front: sin permisos AWS propios, toda llamada a AWS pasa por la API"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-ecs-task-front-role" }
}

resource "aws_cloudwatch_log_group" "ecs_front" {
  name              = "/ecs/${var.project_name}-front"
  retention_in_days = 30

  tags = { Name = "${var.project_name}-ecs-front-logs" }
}

resource "aws_iam_role_policy" "ecs_execution_logs_front" {
  name = "cloudwatch-logs-front"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.ecs_front.arn}:*"
    }]
  })
}

resource "aws_ecs_task_definition" "front" {
  family                   = "${var.project_name}-front"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.front_task_cpu
  memory                   = var.front_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_front.arn

  container_definitions = jsonencode([
    {
      name      = "front"
      image     = "${aws_ecr_repository.front.repository_url}:${var.front_image_tag}"
      essential = true

      portMappings = [{ name = "front", containerPort = 3000, protocol = "tcp" }]

      readonlyRootFilesystem = true
      user                   = "1000:1000"
      privileged             = false

      linuxParameters = {
        capabilities = { drop = ["ALL"], add = [] }
        tmpfs = [
          { containerPath = "/tmp", size = 64 },
          # Next.js standalone escribe cache de build/imagenes aca en
          # runtime aunque el FS del contenedor sea de solo lectura.
          { containerPath = "/app/.next/cache", size = 128 }
        ]
      }

      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "NEXTAUTH_URL", value = var.domain_name != "" ? "https://app.${var.domain_name}" : "" },
        { name = "NEXT_PUBLIC_API_URL", value = var.domain_name != "" ? "https://api.${var.domain_name}" : "" },
        # Service Connect: llega a la API sin salir de la VPC (ver Q8).
        # Usado por el callback server-side de NextAuth y por el SDK del
        # front — nunca por el navegador (eso sigue yendo por dominio
        # publico via NEXT_PUBLIC_API_URL).
        { name = "INTERNAL_API_URL", value = "http://api:8000" },
        { name = "TEK_SECRETS_API_URL", value = "http://api:8000" },
        { name = "TEK_SECRETS_ENVIRONMENT", value = var.sdk_demo_environment_id }
      ]

      secrets = [
        { name = "GITHUB_ID", valueFrom = aws_secretsmanager_secret.github_client_id.arn },
        { name = "GITHUB_SECRET", valueFrom = aws_secretsmanager_secret.github_client_secret.arn },
        { name = "NEXTAUTH_SECRET", valueFrom = aws_secretsmanager_secret.nextauth_secret.arn },
        { name = "TEK_SECRETS_TOKEN", valueFrom = aws_secretsmanager_secret.sdk_demo_token.arn }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_front.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      # wget (BusyBox, ya viene en node:*-alpine), no "node -e fetch": levantar
      # un proceso Node/V8 entero cada 30s en 0.25 vCPU compite por CPU con el
      # propio server y puede pasarse del timeout bajo throttling real —
      # confirmado en Fargate (tasks matados por "failed container health
      # checks" pese a loguear "Ready" casi al instante). wget es ~10x mas
      # liviano. 127.0.0.1 explicito, no "localhost" — musl (Alpine) resuelve
      # localhost a ::1 (IPv6) primero y el server solo escucha IPv4.
      healthCheck = {
        command     = ["CMD-SHELL", "wget --no-verbose --tries=1 --timeout=5 --spider http://127.0.0.1:3000/ || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }

      ulimits = [{ name = "nofile", softLimit = 1024, hardLimit = 4096 }]
    }
  ])

  tags = { Name = "${var.project_name}-task-def-front" }
}

resource "aws_ecs_service" "front" {
  name            = "${var.project_name}-front-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.front.arn
  desired_count   = var.front_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = var.front_desired_count
  }

  network_configuration {
    subnets          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.front.arn
    container_name   = "front"
    container_port   = 3000
  }

  # Solo cliente: front consume "api:8000", no publica nada para que otros
  # descubran — no lleva bloque service{}.
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
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

  # GitHub Actions registra una task definition nueva en cada deploy y
  # actualiza el servicio directamente (ver Q7) — Terraform no debe
  # revertir eso en el proximo apply.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [
    # tg.front SOLO se asocia al ALB via aws_lb_listener_rule.front_host
    # (a diferencia de tg.api, ningun listener lo usa como default action)
    # — sin este depends_on explicito, ECS puede intentar crear el service
    # antes de que exista esa regla y tira "does not have an associated
    # load balancer".
    aws_lb_listener.https,
    aws_lb_listener_rule.front_host,
    aws_iam_role_policy.ecs_execution_ecr,
    aws_iam_role_policy.ecs_execution_logs_front,
    aws_iam_role_policy.ecs_execution_secrets,
    aws_ecs_cluster_capacity_providers.main,
  ]

  tags = { Name = "${var.project_name}-front-service" }
}

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
