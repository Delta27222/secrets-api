# ============================================================================
# Infraestructura de LOGS (QuestDB) — módulo independiente
# NO comparte estado ni recursos con el módulo de rotación (../rotation).
#
# Provisiona: EC2 con QuestDB (Docker) + volumen EBS persistente + Elastic IP
# (IP fija) + Security Group + cola SQS (+ DLQ) para ingesta asíncrona de logs.
# ============================================================================

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---- AMI Amazon Linux 2023 (si no se fija una manualmente) ----
data "aws_ami" "al2023" {
  count       = var.ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  ami_id = var.ami_id != "" ? var.ami_id : data.aws_ami.al2023[0].id
  name   = "${var.project_name}-questdb"
}

# ============================================================================
# 1. Security Group — acceso restringido a los puertos de QuestDB
# ============================================================================
resource "aws_security_group" "questdb" {
  name        = "${local.name}-sg"
  description = "QuestDB (logs): REST/web 9000, PG 8812, ILP 9009"

  ingress {
    description = "QuestDB HTTP/REST + consola web"
    from_port   = 9000
    to_port     = 9000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr
  }

  ingress {
    description = "QuestDB protocolo Postgres (wire)"
    from_port   = 8812
    to_port     = 8812
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr
  }

  ingress {
    description = "QuestDB ingest ILP"
    from_port   = 9009
    to_port     = 9009
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr
  }

  # SSH opcional (solo si se define ssh_cidr)
  dynamic "ingress" {
    for_each = var.ssh_cidr != "" ? [1] : []
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [var.ssh_cidr]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-sg" }
}

# ============================================================================
# 2. Volumen EBS persistente para los datos de QuestDB
# ============================================================================
resource "aws_ebs_volume" "questdb_data" {
  availability_zone = var.availability_zone
  size              = var.data_volume_size
  type              = "gp3"
  tags              = { Name = "${local.name}-data" }
}

# ============================================================================
# 3. Instancia EC2 con QuestDB (instalado vía user_data → Docker)
# ============================================================================
resource "aws_instance" "questdb" {
  ami                    = local.ami_id
  instance_type          = var.instance_type
  availability_zone      = var.availability_zone
  vpc_security_group_ids = [aws_security_group.questdb.id]
  key_name               = var.key_name != "" ? var.key_name : null

  user_data = templatefile("${path.module}/../scripts/questdb_userdata.sh", {
    questdb_version = var.questdb_version
  })

  root_block_device {
    volume_size = var.root_volume_size
    volume_type = "gp3"
  }

  tags = { Name = local.name }
}

resource "aws_volume_attachment" "questdb_data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.questdb_data.id
  instance_id = aws_instance.questdb.id
}

# ============================================================================
# 4. Elastic IP — IP pública fija (para que EC2_INSTANCE_IP no cambie)
# ============================================================================
resource "aws_eip" "questdb" {
  domain   = "vpc"
  instance = aws_instance.questdb.id
  tags     = { Name = "${local.name}-eip" }
}

# ============================================================================
# 5. SQS para ingesta asíncrona de logs (+ DLQ)
# ============================================================================
resource "aws_sqs_queue" "logs_dlq" {
  name = "${var.project_name}-logs-dlq"
  tags = { Name = "${var.project_name}-logs-dlq" }
}

resource "aws_sqs_queue" "logs" {
  name                       = "${var.project_name}-logs-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = var.sqs_message_retention
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.logs_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })
  tags = { Name = "${var.project_name}-logs-queue" }
}
