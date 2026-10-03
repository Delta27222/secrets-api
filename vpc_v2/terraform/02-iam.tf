# ============================================================================
# Grupo 2 — IAM (roles, mínimo privilegio)
#
# Solo se crean aquí los roles y las políticas que NO dependen de recursos
# de grupos futuros (ECR, log groups, colas SQS se referencian por ARN
# construido, no por atributo de recurso, así que no generan dependencia
# de Terraform hacia adelante).
#
# Las políticas que sí dependen de un recurso concreto (pull de ECR, logs de
# CloudWatch) se agregan como aws_iam_role_policy en el archivo del grupo
# donde ese recurso se crea, referenciando el rol de aquí hacia atrás:
#   - ecs_execution: ecr-pull  -> grupo 3 (ECR)
#   - ecs_execution: cloudwatch-logs -> grupo 4 (ECS log group)
#   - ec2_data: ecr-pull-db-images  -> grupo 3 (ECR)
# ============================================================================

data "aws_caller_identity" "current" {}

# ---- 1. ECS Execution Role (agente ECS: pull imagen, logs, secrets) ----

resource "aws_iam_role" "ecs_execution" {
  name = "${var.project_name}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-ecs-execution-role" }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "secrets-manager-read"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/*"
    }]
  })
}

# ---- 2. ECS Task Role (código de la app FastAPI) ----

resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-ecs-task-role" }
}

resource "aws_iam_role_policy" "ecs_task_sqs" {
  name = "sqs-send-only"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["sqs:SendMessage", "sqs:GetQueueUrl"]
      Resource = [
        "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-logs-queue",
        "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-rotation-queue"
      ]
    }]
  })
}

# ---- 3. Lambda Consumer Role (SQS logs -> QuestDB) ----

resource "aws_iam_role" "lambda_consumer" {
  name = "${var.project_name}-lambda-consumer-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-lambda-consumer-role" }
}

resource "aws_iam_role_policy" "lambda_consumer_sqs" {
  name = "sqs-consume-logs"
  role = aws_iam_role.lambda_consumer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-logs-queue"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_consumer_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.lambda_consumer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-logs-consumer:*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_consumer_vpc" {
  name = "vpc-network-interfaces"
  role = aws_iam_role.lambda_consumer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
      Resource = "*"
    }]
  })
}

# ---- 4. Lambda Rotation Role (EventBridge -> Lambda -> SQS) ----

resource "aws_iam_role" "lambda_rotation" {
  name = "${var.project_name}-lambda-rotation-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-lambda-rotation-role" }
}

resource "aws_iam_role_policy" "lambda_rotation_sqs" {
  name = "sqs-rotation"
  role = aws_iam_role.lambda_rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SendToRotationQueue"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-rotation-queue"
      },
      {
        Sid      = "ConsumeFromRotationQueue"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-rotation-queue"
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_rotation_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.lambda_rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-rotation-*:*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_rotation_vpc" {
  name = "vpc-network-interfaces"
  role = aws_iam_role.lambda_rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
      Resource = "*"
    }]
  })
}

# ---- 5. EC2 Data Role (QuestDB + MongoDB: SSM, sin SSH) ----

resource "aws_iam_role" "ec2_data" {
  name        = "${var.project_name}-ec2-data-role"
  description = "Rol para instancias EC2 en subredes de datos: acceso SSM y ECR sin internet"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-ec2-data-role" }
}

resource "aws_iam_role_policy_attachment" "ec2_data_ssm" {
  role       = aws_iam_role.ec2_data.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_data" {
  name = "${var.project_name}-ec2-data-profile"
  role = aws_iam_role.ec2_data.name

  tags = { Name = "${var.project_name}-ec2-data-profile" }
}
